#!/usr/bin/env swift
import Foundation

// Narrow, version-checked diagnostic patch: leaves OAuth, credentials and SDK
// persistence intact. The SPM package is already symlinked to node_modules.
let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let package = root.appendingPathComponent("node_modules/@capacitor-firebase/authentication")
func replace(_ source: inout String, _ before: String, _ after: String) throws {
    if source.contains(after) { return }
    guard source.components(separatedBy: before).count == 2 else {
        throw NSError(domain: "MODUSAuthPatch", code: 1, userInfo: [NSLocalizedDescriptionKey: "Native auth source changed; inspect the diagnostic patch before building."])
    }
    source = source.replacingOccurrences(of: before, with: after)
}
do {
    let metadata = try JSONSerialization.jsonObject(with: Data(contentsOf: package.appendingPathComponent("package.json"))) as! [String: Any]
    guard metadata["version"] as? String == "8.5.2" else { throw NSError(domain: "MODUSAuthPatch", code: 2) }
    let file = package.appendingPathComponent("ios/Plugin/FirebaseAuthentication.swift")
    var source = try String(contentsOf: file, encoding: .utf8)
    try replace(&source, "func handleFailedSignIn(message: String?, error: Error?) {", "func handleFailedSignIn(message: String?, error: Error?, stage: String = \"firebase-authentication\") {")
    try replace(&source,
        "let code = FirebaseAuthenticationHelper.createErrorCode(error: error)\n        savedCall.reject(errorMessage, code)\n    }\n\n    func handleSuccessfulLink",
        "let code = FirebaseAuthenticationHelper.createErrorCode(error: error)\n        let diagnostics = ModusAuthDiagnostics.details(stage: stage, error: error)\n        savedCall.reject(errorMessage, code, nil, diagnostics)\n    }\n\n    func handleSuccessfulLink")
    try replace(&source,
        "Auth.auth().signIn(with: credential) { (authResult, error) in\n            if let error = error {\n                self.handleFailedSignIn(message: nil, error: error)",
        "_ = ModusAuthDiagnostics.details(stage: \"firebase-credential-exchange-start\")\n        Auth.auth().signIn(with: credential) { (authResult, error) in\n            if let error = error {\n                self.handleFailedSignIn(message: nil, error: error, stage: \"firebase-credential-exchange\")")
    try replace(&source,
        "self.handleFailedSignIn(message: nil, error: error, stage: \"firebase-credential-exchange\")\n                return\n            }\n            guard let savedCall",
        "self.handleFailedSignIn(message: nil, error: error, stage: \"firebase-credential-exchange\")\n                return\n            }\n            _ = ModusAuthDiagnostics.details(stage: authResult?.additionalUserInfo?.isNewUser == true ? \"firebase-new-user-authenticated\" : \"firebase-returning-user-authenticated\")\n            guard let savedCall")
    if !source.contains("enum ModusAuthDiagnostics {") {
        source += "\n" + (try String(contentsOf: root.appendingPathComponent("scripts/AuthDiagnostics.swift"), encoding: .utf8))
    }
    let googleFile = package.appendingPathComponent("ios/Plugin/Handlers/GoogleAuthProviderHandler.swift")
    var google = try String(contentsOf: googleFile, encoding: .utf8)
    try replace(&google,
        "self.pluginImplementation.handleFailedSignIn(message: nil, error: error)",
        "self.pluginImplementation.handleFailedSignIn(message: nil, error: error, stage: \"google-authorization-or-token-exchange\")")
    try replace(&google, "DispatchQueue.main.async {", "_ = ModusAuthDiagnostics.details(stage: \"google-sign-in-start\")\n        DispatchQueue.main.async {")
    // Validate every replacement before writing either source file.
    try source.write(to: file, atomically: true, encoding: .utf8)
    try google.write(to: googleFile, atomically: true, encoding: .utf8)
    print("MODUS native authentication diagnostics applied (8.5.2).")
} catch {
    fputs("MODUS auth patch failed: \(error.localizedDescription)\n", stderr)
    exit(1)
}
