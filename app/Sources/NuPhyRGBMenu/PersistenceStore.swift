import Foundation
import os

private let log = Logger(subsystem: "com.nuphy-rgb.menu", category: "PersistenceStore")

/// Reads and writes per-effect parameter override files used by the daemon
/// at startup. The daemon loads the same path — see
/// `src/nuphy_rgb/param_store.py`. Swift is the only writer.
enum PersistenceStore {
    /// `~/.config/nuphy-rgb/params/` — matches the daemon's `params_dir()`.
    static func paramsDir() -> URL {
        let home = FileManager.default.homeDirectoryForCurrentUser
        return home
            .appending(path: ".config", directoryHint: .isDirectory)
            .appending(path: "nuphy-rgb", directoryHint: .isDirectory)
            .appending(path: "params", directoryHint: .isDirectory)
    }

    private static func fileURL(for effect: String) -> URL {
        paramsDir().appending(path: "\(effect).json", directoryHint: .notDirectory)
    }

    /// Atomic write of `{name: value}` overrides for one effect.
    static func save(effect: String, values: [String: Double]) {
        let dir = paramsDir()
        do {
            try FileManager.default.createDirectory(
                at: dir,
                withIntermediateDirectories: true,
            )
            let data = try JSONSerialization.data(
                withJSONObject: values,
                options: [.prettyPrinted, .sortedKeys],
            )
            try data.write(to: fileURL(for: effect), options: .atomic)
        } catch {
            log.warning(
                "failed to save overrides for \(effect, privacy: .public): \(error.localizedDescription, privacy: .public)",
            )
        }
    }

    /// Delete the override file for an effect. Silent if it doesn't exist.
    static func clear(effect: String) {
        let url = fileURL(for: effect)
        do {
            try FileManager.default.removeItem(at: url)
        } catch CocoaError.fileNoSuchFile {
            // fine
        } catch let error as NSError where error.code == NSFileNoSuchFileError {
            // fine
        } catch {
            log.warning(
                "failed to clear overrides for \(effect, privacy: .public): \(error.localizedDescription, privacy: .public)",
            )
        }
    }
}
