"""CoreAudio Process Tap for macOS system audio capture (macOS 14.2+).

Creates a global audio tap + aggregate input device and delivers audio via a
ctypes IOProc callback into a :class:`queue.SimpleQueue`.  The queue is
consumed by :class:`AudioCapture` the same way it consumes PortAudio frames.

This module is macOS-only.  All heavy imports are lazy so it can be imported
on any platform without error — use :func:`is_available` to gate usage.
"""

from __future__ import annotations

import logging
import queue

import numpy as np

log = logging.getLogger(__name__)

_available: bool | None = None


def is_available() -> bool:
    """Return True if the CoreAudio Process Tap API is usable."""
    global _available
    if _available is None:
        try:
            import platform

            ver = tuple(int(x) for x in platform.mac_ver()[0].split(".")[:2])
            if ver < (14, 2):
                _available = False
            else:
                from CoreAudio import AudioHardwareCreateProcessTap  # noqa: F401

                _available = True
        except (ImportError, ValueError):
            _available = False
    return _available


# ---------------------------------------------------------------------------
# ctypes plumbing — loaded lazily inside ProcessTap.start()
# ---------------------------------------------------------------------------

def _load_ctypes_bindings():
    """Return the CoreAudio cdll with IOProc function signatures configured."""
    import ctypes

    ca = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
    )

    ioproc_type = ctypes.CFUNCTYPE(
        ctypes.c_int32,   # return OSStatus
        ctypes.c_uint32,  # device_id
        ctypes.c_void_p,  # inNow
        ctypes.c_void_p,  # inInputData  (AudioBufferList*)
        ctypes.c_void_p,  # inInputTime
        ctypes.c_void_p,  # outOutputData
        ctypes.c_void_p,  # inOutputTime
        ctypes.c_void_p,  # clientData
    )

    ca.AudioDeviceCreateIOProcID.argtypes = [
        ctypes.c_uint32,
        ioproc_type,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ca.AudioDeviceCreateIOProcID.restype = ctypes.c_int32

    ca.AudioDeviceStart.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    ca.AudioDeviceStart.restype = ctypes.c_int32

    ca.AudioDeviceStop.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    ca.AudioDeviceStop.restype = ctypes.c_int32

    ca.AudioDeviceDestroyIOProcID.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    ca.AudioDeviceDestroyIOProcID.restype = ctypes.c_int32

    return ca, ioproc_type


# ---------------------------------------------------------------------------
# AudioBufferList structs for reading IOProc input data
# ---------------------------------------------------------------------------

def _define_abl_structs():
    import ctypes

    class AudioBuffer(ctypes.Structure):
        _fields_ = [
            ("mNumberChannels", ctypes.c_uint32),
            ("mDataByteSize", ctypes.c_uint32),
            ("mData", ctypes.c_void_p),
        ]

    class AudioBufferList(ctypes.Structure):
        _fields_ = [
            ("mNumberBuffers", ctypes.c_uint32),
            ("mBuffers", AudioBuffer * 8),
        ]

    return AudioBufferList


class ProcessTap:
    """Context manager that captures system audio via CoreAudio Process Tap.

    On :meth:`start`, creates the tap + aggregate device + IOProc and begins
    delivering mono float32 chunks into :attr:`queue`.  On :meth:`stop` (or
    context-manager exit), tears everything down in the correct order.

    Usage::

        tap = ProcessTap()
        with tap:
            audio = AudioCapture(external_queue=tap.queue)
            audio.start()
            ...
    """

    def __init__(self) -> None:
        self.queue: queue.SimpleQueue[np.ndarray] = queue.SimpleQueue()
        self._tap_id: int | None = None
        self._agg_id: int | None = None
        self._proc_id = None  # ctypes.c_void_p — kept alive
        self._io_proc_ref = None  # prevent GC of ctypes callback
        self._ca = None  # ctypes CoreAudio bindings
        self._started = False

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Create tap, aggregate device, and IOProc.  Begin capturing."""
        if self._started:
            raise RuntimeError("ProcessTap already started")

        import ctypes
        import uuid
        import warnings

        import objc
        from CoreAudio import (
            AudioHardwareCreateAggregateDevice,
            AudioHardwareCreateProcessTap,
            AudioHardwareDestroyProcessTap,
            kAudioHardwareNoError,
        )

        warnings.filterwarnings("ignore", "PyObjCPointer")

        ca, ioproc_type = _load_ctypes_bindings()
        self._ca = ca

        AudioBufferList = _define_abl_structs()

        # 1. Create tap
        CATapDescription = objc.lookUpClass("CATapDescription")
        desc = CATapDescription.alloc().initStereoGlobalTapButExcludeProcesses_([])
        desc.setName_("NuPhyRGBTap")
        desc.setPrivate_(True)
        desc.setMuteBehavior_(0)  # CATapUnmuted — audio still plays

        status, tap_id = AudioHardwareCreateProcessTap(desc, None)
        if status != kAudioHardwareNoError:
            raise RuntimeError(
                f"AudioHardwareCreateProcessTap failed (status={status})"
            )
        self._tap_id = tap_id
        tap_uuid = str(desc.UUID())
        log.debug("Process tap created: id=%d uuid=%s", tap_id, tap_uuid)

        # 2. Create aggregate device
        agg_uid = f"com.nuphy-rgb.tap.{uuid.uuid4().hex[:8]}"
        config = {
            "name": "NuPhyRGBTap",
            "uid": agg_uid,
            "private": True,
            "stacked": False,
            "taps": [{"uid": tap_uuid, "drift": True}],
            "tapautostart": True,
        }
        status, agg_id = AudioHardwareCreateAggregateDevice(config, None)
        if status != kAudioHardwareNoError:
            AudioHardwareDestroyProcessTap(self._tap_id)
            self._tap_id = None
            raise RuntimeError(
                f"AudioHardwareCreateAggregateDevice failed (status={status})"
            )
        self._agg_id = agg_id
        log.debug("Aggregate device created: id=%d uid=%s", agg_id, agg_uid)

        # 3. Build IOProc callback
        q = self.queue

        @ioproc_type
        def io_proc(device_id, now, input_data, input_time,
                    output_data, output_time, client_data):
            if not input_data:
                return 0
            abl = ctypes.cast(
                input_data, ctypes.POINTER(AudioBufferList)
            ).contents
            buf = abl.mBuffers[0]
            n_floats = buf.mDataByteSize // 4
            if not buf.mData or n_floats == 0:
                return 0
            arr = np.ctypeslib.as_array(
                ctypes.cast(buf.mData, ctypes.POINTER(ctypes.c_float)),
                shape=(n_floats,),
            ).copy()  # copy — buffer is only valid during callback
            # Stereo interleaved → mono downmix
            if buf.mNumberChannels == 2:
                arr = (arr[0::2] + arr[1::2]) * 0.5
            q.put_nowait(arr)
            return 0

        self._io_proc_ref = io_proc  # prevent GC

        # 4. Register and start IOProc
        proc_id = ctypes.c_void_p()
        status = ca.AudioDeviceCreateIOProcID(
            agg_id, io_proc, None, ctypes.byref(proc_id)
        )
        if status != 0:
            self._cleanup_tap_and_agg()
            raise RuntimeError(
                f"AudioDeviceCreateIOProcID failed (status={status})"
            )
        self._proc_id = proc_id

        status = ca.AudioDeviceStart(ctypes.c_uint32(agg_id), proc_id)
        if status != 0:
            ca.AudioDeviceDestroyIOProcID(ctypes.c_uint32(agg_id), proc_id)
            self._proc_id = None
            self._cleanup_tap_and_agg()
            raise RuntimeError(f"AudioDeviceStart failed (status={status})")

        self._started = True
        log.info("CoreAudio Process Tap capturing system audio")

    def stop(self) -> None:
        """Tear down IOProc, aggregate device, and tap.  Idempotent."""
        if not self._started:
            return

        import ctypes

        ca = self._ca
        agg_id = self._agg_id

        # Stop and destroy IOProc
        if self._proc_id is not None and ca is not None and agg_id is not None:
            try:
                ca.AudioDeviceStop(ctypes.c_uint32(agg_id), self._proc_id)
            except Exception:
                log.debug("AudioDeviceStop failed", exc_info=True)
            try:
                ca.AudioDeviceDestroyIOProcID(
                    ctypes.c_uint32(agg_id), self._proc_id
                )
            except Exception:
                log.debug("AudioDeviceDestroyIOProcID failed", exc_info=True)
            self._proc_id = None

        self._io_proc_ref = None
        self._cleanup_tap_and_agg()
        self._started = False
        log.debug("Process tap stopped")

    def _cleanup_tap_and_agg(self) -> None:
        from CoreAudio import (
            AudioHardwareDestroyAggregateDevice,
            AudioHardwareDestroyProcessTap,
        )

        if self._agg_id is not None:
            try:
                AudioHardwareDestroyAggregateDevice(self._agg_id)
            except Exception:
                log.debug("DestroyAggregateDevice failed", exc_info=True)
            self._agg_id = None

        if self._tap_id is not None:
            try:
                AudioHardwareDestroyProcessTap(self._tap_id)
            except Exception:
                log.debug("DestroyProcessTap failed", exc_info=True)
            self._tap_id = None

    # -- context manager -----------------------------------------------------

    def __enter__(self) -> ProcessTap:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def __del__(self) -> None:
        try:
            self.stop()
        except Exception:
            pass  # imports may fail during interpreter shutdown
