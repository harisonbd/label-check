#!/usr/bin/env bash
# v2.45: builds the Label Check Android app on a GitHub runner (called by .github/workflows/apk.yml).
# Capacitor 8, "remote URL": the app opens https://harisonbd.github.io/label-check/, so new website versions arrive by
# themselves. This script makes a fresh Android project each time (nothing Android-specific is kept in the repo), adds the
# camera permission, our MainActivity (share menu for files), the icon, the version, signs the APK with the key from the
# secrets, and puts it on the Releases page (Obtainium reads it from there).
set -euo pipefail
ROOT="$(pwd)"; HERE="$ROOT/tools/apk"; RUN="${RUN:-0}"; VER="1.0.$RUN"
if [ -z "${APK_KEYSTORE_B64:-}" ] || [ -z "${APK_KEYSTORE_PASS:-}" ]; then
  echo "::error::The secrets APK_KEYSTORE_B64 and APK_KEYSTORE_PASS are missing (repo Settings -> Secrets and variables -> Actions)."
  exit 1
fi

echo "== tools"
N22="$(ls -d /opt/hostedtoolcache/node/2[2-9].*/x64 2>/dev/null | sort -V | tail -1 || true)"   # Capacitor 8 needs Node 22+
if [ -n "$N22" ]; then export PATH="$N22/bin:$PATH"; fi
export JAVA_HOME="${JAVA_HOME_21_X64:-${JAVA_HOME:-}}"                                           # and JDK 21
export PATH="$JAVA_HOME/bin:$PATH"
node -v; java -version 2>&1 | head -1; echo "ANDROID_HOME=$ANDROID_HOME"

echo "== Capacitor project"
W="${RUNNER_TEMP:-/tmp}/lc-apk"; rm -rf "$W"; mkdir -p "$W/www"; cd "$W"
cp "$HERE/package.json" "$HERE/capacitor.config.json" .
cp "$HERE/www/index.html" www/index.html
npm install --no-audit --no-fund
npx cap add android
APPDIR="$W/android/app"; RES="$APPDIR/src/main/res"; MAN="$APPDIR/src/main/AndroidManifest.xml"

echo "== camera permission (barcode scanner, product photo)"
grep -q 'android.permission.CAMERA' "$MAN" || sed -i 's#<uses-permission android:name="android.permission.INTERNET" />#&\n    <uses-permission android:name="android.permission.CAMERA" />#' "$MAN"
grep -q 'android.permission.CAMERA' "$MAN" || { echo "::error::Could not add the camera permission"; cat "$MAN"; exit 1; }

echo "== MainActivity with the share menu (LCNative)"
MA="$(find "$APPDIR/src/main/java" -name MainActivity.java | head -1)"
[ -n "$MA" ] || { echo "::error::MainActivity.java not found"; find "$APPDIR/src/main" -maxdepth 6 | head -50; exit 1; }
cp "$HERE/MainActivity.java" "$MA"
mkdir -p "$RES/xml"; cp "$HERE/file_paths.xml" "$RES/xml/file_paths.xml"
grep -q 'androidx.core.content.FileProvider' "$MAN" || { echo "::error::The FileProvider is not in the manifest"; cat "$MAN"; exit 1; }

echo "== version $VER ($RUN)"
sed -i -E "s/versionCode [0-9]+/versionCode $RUN/; s/versionName \"[^\"]*\"/versionName \"$VER\"/" "$APPDIR/build.gradle"
grep -E 'versionCode|versionName' "$APPDIR/build.gradle"

echo "== icon and start screen"
IM="$(command -v magick || command -v convert || true)"
if [ -n "$IM" ]; then
  rm -rf "$RES/mipmap-anydpi-v26"
  for d in mdpi:48 hdpi:72 xhdpi:96 xxhdpi:144 xxxhdpi:192; do
    n="${d%%:*}"; s="${d##*:}"; mkdir -p "$RES/mipmap-$n"
    "$IM" "$ROOT/icon-512.png" -resize "${s}x${s}" "$RES/mipmap-$n/ic_launcher.png"
    cp "$RES/mipmap-$n/ic_launcher.png" "$RES/mipmap-$n/ic_launcher_round.png"
  done
  find "$RES" -name 'splash.png' | while read -r f; do
    sz="$(identify -format '%wx%h' "$f")"; m="$(identify -format '%[fx:int(min(w,h)/3)]' "$f")"
    "$IM" -size "$sz" xc:'#121417' \( "$ROOT/icon-512.png" -resize "${m}x${m}" \) -gravity center -composite "$f"
  done
else
  echo "::warning::ImageMagick not found: the default Capacitor icon stays"
fi

echo "== build"
cd "$W/android"; chmod +x gradlew
./gradlew --no-daemon --stacktrace assembleRelease
UNS="$(find app/build/outputs/apk/release -name '*.apk' | head -1)"
[ -n "$UNS" ] || { echo "::error::No APK was built"; exit 1; }

echo "== sign"
BT="$(ls -d "$ANDROID_HOME"/build-tools/* | sort -V | tail -1)"
umask 077; printf '%s' "$APK_KEYSTORE_B64" | base64 -d > "$W/key.p12"
"$BT/zipalign" -f -p 4 "$UNS" "$W/aligned.apk"
"$BT/apksigner" sign --ks "$W/key.p12" --ks-type PKCS12 --ks-key-alias labelcheck \
  --ks-pass env:APK_KEYSTORE_PASS --key-pass env:APK_KEYSTORE_PASS --out "$W/label-check.apk" "$W/aligned.apk"
rm -f "$W/key.p12"
"$BT/apksigner" verify --print-certs "$W/label-check.apk" | grep -i 'SHA-256' | head -2
ls -la "$W/label-check.apk"

echo "== publish on the Releases page"
cd "$ROOT"
sha256sum "$W/label-check.apk" | cut -d' ' -f1 > "$W/label-check.apk.sha256"
gh release create "apk-$VER" "$W/label-check.apk" "$W/label-check.apk.sha256" --latest \
  --title "Label Check app $VER" \
  --notes "Android app for Label Check. It opens https://harisonbd.github.io/label-check/ (new versions of the website arrive by themselves). Install the APK, or let Obtainium keep it up to date: add https://github.com/harisonbd/label-check in Obtainium. Signing certificate SHA-256: see the build log."
echo "done: apk-$VER"
