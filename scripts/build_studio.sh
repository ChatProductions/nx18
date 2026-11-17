#!/bin/bash
# macOS CI compiles a reusable UNSIGNED iOS 17+ inspection app.
# No Apple Developer account, signing key, game content, or Nintendo keys needed.
set -euo pipefail
cd "$(dirname "$0")/.."

SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
ROOT="$PWD"
OUT="$ROOT/build/ios"
APP="$OUT/Payload/NX18Studio.app"
rm -rf "$OUT"
mkdir -p "$APP"

xcrun swiftc -O -parse-as-library -swift-version 5 \
  -sdk "$SDK" -target arm64-apple-ios17.0 \
  -module-name NX18Studio \
  -framework SwiftUI -framework UniformTypeIdentifiers \
  "$ROOT/Studio/NSPInspector.swift" \
  "$ROOT/Studio/NSPExtractor.swift" \
  "$ROOT/Studio/MetalProbe.swift" \
  "$ROOT/Studio/NCAHeader.swift" \
  "$ROOT/Studio/NCAPayload.swift" \
  "$ROOT/Runtime/BCDecode.swift" \
  "$ROOT/Studio/NX18App.swift" \
  -o "$APP/NX18Studio"

cp "$ROOT/Studio/Info.plist" "$APP/Info.plist"
plutil -lint "$APP/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :MinimumOSVersion' "$APP/Info.plist" | grep -Fx '17.0'
file "$APP/NX18Studio"
# Fail if the Mac compiler accidentally moves the minimum iOS version to 26.
xcrun vtool -show-build "$APP/NX18Studio" | tee "$OUT/macho-build-version.txt"
grep -Eq "minos[[:space:]]+17[.]0" "$OUT/macho-build-version.txt" || {
  echo "Unexpected Mach-O deployment target"; exit 1;
}
if otool -L "$APP/NX18Studio" | grep -q "libswift_DarwinFoundation2"; then
  echo "ERROR: iOS 26 Swift runtime dependency detected"; exit 1
fi

(
  cd "$OUT"
  /usr/bin/zip -qr "nx18-studio-unsigned.ipa" Payload
  /usr/bin/unzip -t "nx18-studio-unsigned.ipa" | tail -1
)
echo "Output: $OUT/nx18-studio-unsigned.ipa"
echo "This is an unsigned NSP inspector, NOT an AC2 port."
