#!/bin/bash

. ../activate

set -e
if [ ! "$1" ]; then
  echo "This script requires either amd64 of arm64 as an argument"
	exit 1
elif [ "$1" = "amd64" ]; then
	PLATFORM="$1"
	DIR_NAME="cryptodoge-linux-x64"
else
	PLATFORM="$1"
	DIR_NAME="cryptodoge-linux-arm64"
fi

pip install setuptools_scm
# The environment variable CRYPTODOGE_INSTALLER_VERSION needs to be defined
# If the env variable NOTARIZE and the username and password variables are
# set, this will attempt to Notarize the signed DMG
CRYPTODOGE_INSTALLER_VERSION=$(python installer-version.py)

if [ ! "$CRYPTODOGE_INSTALLER_VERSION" ]; then
	echo "WARNING: No environment variable CRYPTODOGE_INSTALLER_VERSION set. Using 0.0.0."
	CRYPTODOGE_INSTALLER_VERSION="0.0.0"
fi
echo "Cryptodoge Installer Version is: $CRYPTODOGE_INSTALLER_VERSION"

echo "Installing npm and electron packagers"
cd npm_linux_deb || exit
npm ci
PATH=$(npm bin):$PATH
cd .. || exit

echo "Create dist/"
rm -rf dist
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
cp package.json package.json.orig
jq --arg VER "$CRYPTODOGE_INSTALLER_VERSION" '.version=$VER' package.json > temp.json && mv temp.json package.json

electron-packager . cryptodoge --asar.unpack="**/daemon/**" --platform=linux \
--icon=src/assets/img/Cryptodoge.icns --overwrite --app-bundle-id=net.cryptodoge.blockchain \
--appVersion=$CRYPTODOGE_INSTALLER_VERSION --executable-name=cryptodoge
LAST_EXIT_CODE=$?

# reset the package.json to the original
mv package.json.orig package.json

if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-packager failed!"
	exit $LAST_EXIT_CODE
fi

mv $DIR_NAME ../../../build_scripts/dist/
cd ../../../build_scripts || exit

echo "Create cryptodoge-$CRYPTODOGE_INSTALLER_VERSION.deb"
rm -rf final_installer
mkdir final_installer
electron-installer-debian --src dist/$DIR_NAME/ --dest final_installer/ \
--arch "$PLATFORM" --options.version $CRYPTODOGE_INSTALLER_VERSION --options.bin cryptodoge --options.name cryptodoge
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-installer-debian failed!"
	exit $LAST_EXIT_CODE
fi

ls final_installer/
