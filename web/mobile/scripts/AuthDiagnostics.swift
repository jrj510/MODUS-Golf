// Appended to the pinned native authentication plugin by patch-auth.swift.
// Never serialize NSError.userInfo, descriptions, tokens or full URLs.
enum ModusAuthDiagnostics {
    static func details(stage: String, error: Error? = nil) -> [String: Any] {
        var chain: [[String: Any]] = []
        func visit(_ error: NSError, depth: Int) {
            guard depth < 6, chain.count < 12 else { return }
            var item: [String: Any] = ["domain": error.domain, "code": error.code]
            let url = (error.userInfo[NSURLErrorFailingURLErrorKey] as? URL)
                ?? (error.userInfo[NSURLErrorFailingURLStringErrorKey] as? String).flatMap(URL.init(string:))
            if let host = url?.host { item["hostname"] = host }
            chain.append(item)
            if let underlying = error.userInfo[NSUnderlyingErrorKey] as? NSError {
                visit(underlying, depth: depth + 1)
            }
            if let underlying = error.userInfo["NSMultipleUnderlyingErrors"] as? [NSError] {
                for child in underlying.prefix(6) { visit(child, depth: depth + 1) }
            }
        }
        if let error = error { visit(error as NSError, depth: 0) }
        let result: [String: Any] = ["stage": stage, "nativeErrors": chain,
            "authenticated": Auth.auth().currentUser != nil]
        #if DEBUG
        if let data = try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]),
           let text = String(data: data, encoding: .utf8) {
            print("[MODUS Auth] " + text)
        }
        #endif
        return result
    }
}
