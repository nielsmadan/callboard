// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "CallboardKit",
    platforms: [.macOS(.v15)],
    products: [
        .library(name: "CallboardKit", targets: ["CallboardKit"])
    ],
    dependencies: [
        .package(url: "https://github.com/nielsmadan/ShortcutKit", exact: "0.8.0")
    ],
    targets: [
        .target(
            name: "CallboardKit",
            dependencies: [.product(name: "ShortcutKit", package: "ShortcutKit")]
        ),
        .testTarget(
            name: "CallboardKitTests",
            dependencies: ["CallboardKit"],
            resources: [.copy("Fixtures")]
        )
    ],
    swiftLanguageModes: [.v6]
)
