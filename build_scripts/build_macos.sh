#!/bin/bash

set -euo pipefail

pip install setuptools_scm
# The environment variable CRYPTODOGE_INSTALLER_VERSION needs to be defined.
# If the env variable NOTARIZE and the username and password variables are
# set, this will attempt to Notarize the signed DMG.c
CRYPTODOGE_INSTALLER_VERSION=$(python installer-version.py)

if [ ! "$CRYPTODOGE_INSTALLER_VERSION" ]; then
	echo "WARNING: No environment variable CRYPTODOGE_INSTALLER_VERSION set. Using 0.0.0."
	CRYPTODOGE_INSTALLER_VERSION="0.0.0"
fi
echo "Cryptodoge Installer Version is: $CRYPTODOGE_INSTALLER_VERSION"

echo "Installing npm and electron packagers"
cd npm_macos || exit
npm ci
PATH=$(npm bin):$PATH
cd .. || exit

echo "Create dist/"
sudo rm -rf dist
mkdir dist

echo "Create executables with pyinstaller"
pip install pyinstaller==4.9
SPEC_FILE=$(python -c 'import cryptodoge; print(cryptodoge.PYINSTALLER_SPEC_PATH)')
pyinstaller --log-level=INFO "$SPEC_FILE"
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "pyinstaller failed!"
	exit $LAST_EXIT_CODE
fi
cp -r dist/daemon ../cryptodoge-gui/packages/gui
cd .. || exit
cd cryptodoge-gui || exit

echo "npm build"
lerna clean -y
npm ci
# Audit fix does not currently work with Lerna. See https://github.com/lerna/lerna/issues/1663
# npm audit fix
npm run build
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "npm run build failed!"
	exit $LAST_EXIT_CODE
fi

# Change to the gui package
cd packages/gui || exit

# sets the version for cryptodoge in package.json
brew install jq
cp package.json package.json.orig
jq --arg VER "$CRYPTODOGE_INSTALLER_VERSION" '.version=$VER' package.json > temp.json && mv temp.json package.json

electron-packager . Cryptodoge --asar.unpack="**/daemon/**" --platform=darwin \
--icon=src/assets/img/Cryptodoge.icns --overwrite --app-bundle-id=net.cryptodoge.blockchain \
--appVersion=$CRYPTODOGE_INSTALLER_VERSION
LAST_EXIT_CODE=$?

# reset the package.json to the original
mv package.json.orig package.json

if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-packager failed!"
	exit $LAST_EXIT_CODE
fi

if [ "$NOTARIZE" == true ]; then
  electron-osx-sign Cryptodoge-darwin-x64/Cryptodoge.app --platform=darwin \
  --hardened-runtime=true --provisioning-profile=cryptodoge.provisionprofile \
  --entitlements=entitlements.mac.plist --entitlements-inherit=entitlements.mac.plist \
  --no-gatekeeper-assess
fi
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-osx-sign failed!"
	exit $LAST_EXIT_CODE
fi

mv Cryptodoge-darwin-x64 ../../../build_scripts/dist/
cd ../../../build_scripts || exit

DMG_NAME="Cryptodoge-$CRYPTODOGE_INSTALLER_VERSION.dmg"
echo "Create $DMG_NAME"
mkdir final_installer
NODE_PATH=./npm_macos/node_modules node build_dmg.js dist/Cryptodoge-darwin-x64/Cryptodoge.app $CRYPTODOGE_INSTALLER_VERSION
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-installer-dmg failed!"
	exit $LAST_EXIT_CODE
fi

if [ "$NOTARIZE" == true ]; then
	echo "Notarize $DMG_NAME on ci"
	cd final_installer || exit
  notarize-cli --file=$DMG_NAME --bundle-id net.cryptodoge.blockchain \
	--username "$APPLE_NOTARIZE_USERNAME" --password "$APPLE_NOTARIZE_PASSWORD"
  echo "Notarization step complete"
else
	echo "Not on ci or no secrets so skipping Notarize"
fi

# Notes on how to manually notarize
#
# Ask for username and password. password should be an app specific password.
# Generate app specific password https://support.apple.com/en-us/HT204397
# xcrun altool --notarize-app -f Cryptodoge-0.1.X.dmg --primary-bundle-id net.cryptodoge.blockchain -u username -p password
# xcrun altool --notarize-app; -should return REQUEST-ID, use it in next command
#
# Wait until following command return a success message".
# watch -n 20 'xcrun altool --notarization-info  {REQUEST-ID} -u username -p password'.
# It can take a while, run it every few minutes.
#
# Once that is successful, execute the following command":
# xcrun stapler staple Cryptodoge-0.1.X.dmg
#
# Validate DMG:
# xcrun stapler validate Cryptodoge-0.1.X.dmg
