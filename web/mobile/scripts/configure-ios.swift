// Run by prepare-mac.mjs after checking Swift, Xcode and the Capacitor SPM project.
// This configures resources/Info.plist only. It never parses or edits .pbxproj.
import Foundation

enum SetupError: Error, CustomStringConvertible {
    case invalid(String)
    var description: String { switch self { case .invalid(let message): return message } }
}
func require(_ condition: Bool, _ message: String) throws {
    if !condition { throw SetupError.invalid(message) }
}
func plist(_ url: URL) throws -> [String: Any] {
    let object = try PropertyListSerialization.propertyList(from: Data(contentsOf: url), options: [], format: nil)
    guard let result = object as? [String: Any] else { throw SetupError.invalid("Expected plist dictionary: \(url.path)") }
    return result
}
func json(_ url: URL) throws -> [String: Any] {
    guard let result = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any] else {
        throw SetupError.invalid("Expected JSON dictionary: \(url.path)")
    }
    return result
}

do {
    #if !os(macOS)
    throw SetupError.invalid("Native iOS resource preparation runs on macOS.")
    #endif
    try require(CommandLine.arguments.count == 2, "Pass the absolute mobile package directory.")
    let manager = FileManager.default
    let root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true).standardizedFileURL.resolvingSymlinksInPath()
    let app = root.appendingPathComponent("ios/App/App", isDirectory: true)
    let infoURL = app.appendingPathComponent("Info.plist")
    let firebaseURL = root.appendingPathComponent("firebase/GoogleService-Info.plist")
    let firebase = try plist(firebaseURL)
    let required = try json(root.appendingPathComponent("firebase/Info.plist.required-entries.json"))
    let expected = ["PROJECT_ID": "modus-golf-ea469", "BUNDLE_ID": "com.modusgolf.app", "GOOGLE_APP_ID": "1:759125763752:ios:7e7aacf0f2e63d32dc449d"]
    for (key, value) in expected { try require(firebase[key] as? String == value, "Firebase \(key) mismatch.") }
    let project = root.appendingPathComponent("ios/App/App.xcodeproj/project.pbxproj")
    try require(manager.fileExists(atPath: project.path), "Generate the standard Capacitor iOS project first.")
    try require(app.resolvingSymlinksInPath().path.hasPrefix(root.path + "/"), "Native app directory escapes this package.")
    let scene = try String(contentsOf: app.appendingPathComponent("SceneDelegate.swift"), encoding: .utf8)
    try require(scene.contains("SceneDelegateProxy.shared.scene"), "Inspect the scene URL forwarding before using this custom/older project.")
    var info = try plist(infoURL)
    try require(info["UIApplicationSceneManifest"] != nil, "The generated Capacitor 8.5 scene manifest is missing.")
    let originalFirebase = app.appendingPathComponent("GoogleService-Info.plist")
    if manager.fileExists(atPath: originalFirebase.path) {
        let existing = try plist(originalFirebase)
        try require(existing["GOOGLE_APP_ID"] as? String == expected["GOOGLE_APP_ID"], "The native project already contains another Firebase app. Inspect it before replacing.")
    }
    info["CFBundleDisplayName"] = "MODUS Golf"
    info["GIDClientID"] = required["GIDClientID"]
    info["NSLocalNetworkUsageDescription"] = required["NSLocalNetworkUsageDescription"]
    var ats = info["NSAppTransportSecurity"] as? [String: Any] ?? [:]
    try require(ats["NSAllowsArbitraryLoads"] as? Bool != true, "Inspect the existing blanket ATS exception; this setup does not require one.")
    ats["NSAllowsLocalNetworking"] = true
    info["NSAppTransportSecurity"] = ats
    var urlTypes = info["CFBundleURLTypes"] as? [[String: Any]] ?? []
    guard let scheme = firebase["REVERSED_CLIENT_ID"] as? String else { throw SetupError.invalid("Missing Firebase reversed Google client ID.") }
    if !urlTypes.contains(where: { ($0["CFBundleURLSchemes"] as? [String] ?? []).contains(scheme) }) {
        urlTypes.append(["CFBundleTypeRole": "Editor", "CFBundleURLSchemes": [scheme]])
    }
    info["CFBundleURLTypes"] = urlTypes
    let privacyURL = app.appendingPathComponent("PrivacyInfo.xcprivacy")
    var privacy: [String: Any] = [:]
    if manager.fileExists(atPath: privacyURL.path) { privacy = try plist(privacyURL) }
    var accesses = privacy["NSPrivacyAccessedAPITypes"] as? [[String: Any]] ?? []
    let category = "NSPrivacyAccessedAPICategoryFileTimestamp"
    if let index = accesses.firstIndex(where: { $0["NSPrivacyAccessedAPIType"] as? String == category }) {
        var reasons = accesses[index]["NSPrivacyAccessedAPITypeReasons"] as? [String] ?? []
        if !reasons.contains("C617.1") { reasons.append("C617.1") }
        accesses[index]["NSPrivacyAccessedAPITypeReasons"] = reasons
    } else {
        accesses.append(["NSPrivacyAccessedAPIType": category, "NSPrivacyAccessedAPITypeReasons": ["C617.1"]])
    }
    privacy["NSPrivacyAccessedAPITypes"] = accesses
    let backup = root.appendingPathComponent(".modus-backups/\(UUID().uuidString)", isDirectory: true)
    func write(_ data: Data, to destination: URL) throws {
        try require(destination.resolvingSymlinksInPath().path.hasPrefix(app.resolvingSymlinksInPath().path + "/"), "Resource destination escapes the native app directory.")
        if manager.fileExists(atPath: destination.path) {
            let old = try Data(contentsOf: destination)
            if old == data { return }
            try manager.createDirectory(at: backup, withIntermediateDirectories: true)
            try old.write(to: backup.appendingPathComponent(destination.lastPathComponent), options: .atomic)
        }
        try data.write(to: destination, options: .atomic)
    }
    try write(PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0), to: infoURL)
    try write(Data(contentsOf: firebaseURL), to: originalFirebase)
    try write(PropertyListSerialization.data(fromPropertyList: privacy, format: .xml, options: 0), to: privacyURL)
    print("Configured Info.plist, Firebase plist and Filesystem privacy manifest.")
    print("In Xcode add GoogleService-Info.plist and PrivacyInfo.xcprivacy to the App target's Copy Bundle Resources. File copy alone does not set target membership.")
    print("Verify -ObjC in Other Linker Flags and choose the owner's signing team. No project file or signing identity was changed by this script.")
} catch {
    FileHandle.standardError.write(Data("MODUS native configuration stopped: \(error)\n".utf8))
    exit(1)
}
