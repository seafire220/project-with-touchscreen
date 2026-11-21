#!/usr/bin/env python3
"""Build Character Studio as an app a buyer installs like any other, with its own Python inside:

- Windows: `CharacterStudio-Setup-<version>.exe`, an installer (Inno Setup). It installs for the one
  user, without asking for an administrator; the Start menu (and the desktop, if ticked) get a
  Character Studio icon; it can be removed from Settings -> Apps like any program.
- macOS: `CharacterStudio-<version>.dmg` with `Character Studio.app`, dragged to Applications.
- Linux: `CharacterStudio-<version>-x86_64.AppImage`, one file that runs when double-clicked.

Each opens the studio's page in the browser (launch.py --desktop): the first time, a page shows the
one-time download of its AI tools with its progress, then the studio.

    python3 studio/packaging/build_app.py --python PYTHON_DIR --version 2026.11.21 --out DIST
        [--iscc PATH_TO_ISCC.exe] [--appimagetool PATH --appimage-runtime PATH]

PYTHON_DIR is a relocatable Python 3.12 for the computer being built for (`uv python install 3.12
--install-dir DIR` gets one; the "Make the Character Studio apps" workflow does). The app is built for
the system this runs on. Uses only Python's own library.
"""
import argparse
import compileall
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
ROOT = os.path.dirname(STUDIO)
NAME = "Character Studio"
BUNDLE_ID = "io.github.seafire220.characterstudio"
# The same on every build, so a new version installs over the old one on Windows.
WINDOWS_APP_ID = "{8F3C2A51-6B7D-4E2A-9C1F-2D5E7A9B3C40}"

# Parts of Python the studio never uses: its own tests, the IDLE editor, Tk windows and the like.
PYTHON_LEFT_OUT = {"test", "idlelib", "tkinter", "turtledemo", "turtle.py", "pydoc_data", "lib2to3", "tcl", "tcl8.6",
                   "tk8.6", "tcl8", "share", "__pycache__"}
# _dbm: in the Linux build it has Berkeley DB 6 inside, which is under the GNU AGPL; the studio never uses
# it (Python's dbm module then uses its own simple format).
PYTHON_LEFT_OUT_FILES = re.compile(r"^(_tkinter.*|_dbm\..*|tcl\d.*|tk\d.*|libtcl.*|libtk.*|.*\.a)$")
# Tcl/Tk's own folders (tcl9.0, tk9.0, itcl4.3.5, thread3.0.4, ...): with Tkinter left out, nothing uses them.
PYTHON_LEFT_OUT_DIRS = re.compile(r"^(tcl|tk|itcl|thread|tdbc)\d")


def copy_python(src, dst):
    """The relocatable Python, without what the studio never uses."""
    def ignore(folder, names):
        out = set()
        for n in names:
            if n in PYTHON_LEFT_OUT or PYTHON_LEFT_OUT_FILES.match(n) or PYTHON_LEFT_OUT_DIRS.match(n) or \
                    (n.startswith("config-") and "lib" in folder):
                out.add(n)
        return out
    shutil.copytree(src, dst, symlinks=True, ignore=ignore)
    # Only the app's own environment installs packages, not this copy (some Pythons say so in a file).
    for root, _, files in os.walk(dst):
        if "EXTERNALLY-MANAGED" in files:
            os.remove(os.path.join(root, "EXTERNALLY-MANAGED"))


def copy_studio(dst):
    """The studio's code and page, and the parts of the device's code it uses."""
    os.makedirs(os.path.join(dst, "studio"))
    for name in sorted(os.listdir(STUDIO)):
        path = os.path.join(STUDIO, name)
        if name.endswith(".py") and not name.startswith("test_") and name != "smoke_test.py" or \
                name.startswith("requirements") and name.endswith(".txt"):
            shutil.copy2(path, os.path.join(dst, "studio", name))
    shutil.copytree(os.path.join(STUDIO, "app"), os.path.join(dst, "studio", "app"))
    shutil.copytree(os.path.join(ROOT, "core", "companion"), os.path.join(dst, "core", "companion"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(os.path.join(ROOT, "THIRD_PARTY.md"), os.path.join(dst, "THIRD_PARTY.md"))
    # The app's notice and the licences of the Python inside (the studio's licences page shows them).
    os.makedirs(os.path.join(dst, "licenses"), exist_ok=True)
    shutil.copy2(os.path.join(HERE, "notice.txt"), os.path.join(dst, "licenses", "notice.txt"))
    shutil.copy2(os.path.join(HERE, "python-licences.txt"), os.path.join(dst, "licenses", "python-components.txt"))
    with open(os.path.join(dst, "VERSION"), "w", encoding="utf-8") as f:
        f.write(ARGS.version + "\n")


def precompile(python_exe, *folders):
    """Compile everything once now: the app's own files are not written to when it runs (a signed Mac app
    must not change, and an AppImage cannot)."""
    for folder in folders:
        result = subprocess.run([python_exe, "-m", "compileall", "-q", "-j", "0", folder])
        if result.returncode != 0:
            print("note: some files in %s did not compile (%d)" % (folder, result.returncode))


def payload(dst, python_dir):
    copy_python(python_dir, os.path.join(dst, "python"))
    copy_studio(dst)
    exe = os.path.join(dst, "python", "python.exe") if os.name == "nt" else os.path.join(dst, "python", "bin", "python3")
    precompile(exe, os.path.join(dst, "python"), os.path.join(dst, "studio"), os.path.join(dst, "core"))
    return exe


def check_payload(exe, dst):
    """The copied Python starts, has what setting up needs, and the studio's launcher loads."""
    code = ("import ensurepip, venv, ssl, sqlite3, json, http.server, urllib.request; import sys; "
            "import importlib.util as u; assert u.find_spec('_dbm') is None, 'the AGPL Berkeley DB module is in'; "
            "sys.path.insert(0, r'%s'); import launch; print('python', sys.version.split()[0], 'ok')"
            % os.path.join(dst, "studio"))
    subprocess.run([exe, "-I", "-c", code], check=True)
    for name in ("notice.txt", "python-components.txt"):
        if not os.path.isfile(os.path.join(dst, "licenses", name)):
            raise SystemExit("the app's licences are missing: " + name)


# ------------------------------------------------------------------------------------------------
# Windows: an installer
# ------------------------------------------------------------------------------------------------

ISS = r"""
#define AppName "Character Studio"
[Setup]
AppId={{APP_ID}
AppName={#AppName}
AppVersion=VERSION
AppVerName={#AppName} VERSION
DefaultDirName={localappdata}\Programs\Character Studio
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=OUTPUT
OutputBaseFilename=CharacterStudio-Setup-VERSION
SetupIconFile=SOURCE\icon.ico
UninstallDisplayIcon={app}\icon.ico
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Put Character Studio on the desktop"

[Files]
Source: "SOURCE\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Character Studio"; Filename: "{app}\python\pythonw.exe"; Parameters: "-I -B ""{app}\studio\launch.py"" --desktop"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Comment: "Make a character from a picture"
Name: "{autodesktop}\Character Studio"; Filename: "{app}\python\pythonw.exe"; Parameters: "-I -B ""{app}\studio\launch.py"" --desktop"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Comment: "Make a character from a picture"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-I -B ""{app}\studio\launch.py"" --desktop"; WorkingDir: "{app}"; Description: "Start Character Studio"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{%USERPROFILE}') + '\.character-studio';
    if DirExists(Data) then
      if SuppressibleMsgBox('Also delete the AI tools and the part-finding model that Character Studio downloaded ' +
          '(several GB, in ' + Data + ')?' + #13#10#13#10 +
          'Characters you sent to your device, or saved as .char files, are not affected.',
          mbConfirmation, MB_YESNO, IDNO) = IDYES then
        DelTree(Data, True, True, True);
  end;
end;
"""


def build_windows(work, out, python_dir, iscc):
    src = os.path.join(work, "app")
    exe = payload(src, python_dir)
    check_payload(exe, src)
    shutil.copy2(os.path.join(HERE, "icon.ico"), os.path.join(src, "icon.ico"))
    script = (ISS.replace("APP_ID", WINDOWS_APP_ID.strip("{")).replace("VERSION", ARGS.version)
              .replace("OUTPUT", out).replace("SOURCE", src))
    iss = os.path.join(work, "CharacterStudio.iss")
    with open(iss, "w", encoding="utf-8-sig") as f:
        f.write(script)
    subprocess.run([iscc or "iscc", "/Q", iss], check=True)
    return os.path.join(out, "CharacterStudio-Setup-%s.exe" % ARGS.version)


# ------------------------------------------------------------------------------------------------
# macOS: an app in a disk image
# ------------------------------------------------------------------------------------------------

MAC_MAIN = """#!/bin/bash
# Character Studio: starts the studio; its page opens in the browser (launch.py --desktop).
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
exec "$RES/python/bin/python3" -I -B "$RES/studio/launch.py" --desktop "$@"
"""


def build_mac(work, out, python_dir):
    app = os.path.join(work, "dmg", NAME + ".app")
    contents = os.path.join(app, "Contents")
    resources = os.path.join(contents, "Resources")
    exe = payload(resources, python_dir)
    check_payload(exe, resources)
    os.makedirs(os.path.join(contents, "MacOS"))
    main = os.path.join(contents, "MacOS", NAME)
    with open(main, "w", encoding="utf-8") as f:
        f.write(MAC_MAIN)
    os.chmod(main, 0o755)
    shutil.copy2(os.path.join(HERE, "icon.icns"), os.path.join(resources, "AppIcon.icns"))
    short = ".".join((re.findall(r"\d+", ARGS.version) + ["0", "0"])[:3])
    with open(os.path.join(contents, "Info.plist"), "wb") as f:
        plistlib.dump({
            "CFBundleName": NAME,
            "CFBundleDisplayName": NAME,
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleVersion": ARGS.version,
            "CFBundleShortVersionString": short,
            "CFBundlePackageType": "APPL",
            "CFBundleExecutable": NAME,
            "CFBundleIconFile": "AppIcon",
            "LSMinimumSystemVersion": "12.0",
            # No Dock icon or menu: the studio is its page in the browser, with its own Quit button.
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.graphics-design",
        }, f)
    os.symlink("/Applications", os.path.join(work, "dmg", "Applications"))
    dmg = os.path.join(out, "CharacterStudio-%s.dmg" % ARGS.version)
    subprocess.run(["hdiutil", "create", "-volname", NAME, "-srcfolder", os.path.join(work, "dmg"), "-ov",
                    "-format", "UDZO", dmg], check=True)
    return dmg


# ------------------------------------------------------------------------------------------------
# Linux: an AppImage
# ------------------------------------------------------------------------------------------------

APPRUN = """#!/bin/sh
# Character Studio: starts the studio; its page opens in the browser (launch.py --desktop).
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/python/bin/python3" -I -B "$HERE/usr/studio/launch.py" --desktop "$@"
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=Character Studio
Comment=Make a character from a picture
Exec=AppRun
Icon=character-studio
Categories=Graphics;
Terminal=false
"""


def build_linux(work, out, python_dir, appimagetool, runtime=None):
    appdir = os.path.join(work, "CharacterStudio.AppDir")
    exe = payload(os.path.join(appdir, "usr"), python_dir)
    check_payload(exe, os.path.join(appdir, "usr"))
    # The AppImage runtime's licences (its libfuse is LGPL: its source is published with each release).
    shutil.copy2(os.path.join(HERE, "appimage-runtime-licences.txt"),
                 os.path.join(appdir, "usr", "licenses", "appimage-runtime.txt"))
    with open(os.path.join(appdir, "AppRun"), "w", encoding="utf-8") as f:
        f.write(APPRUN)
    os.chmod(os.path.join(appdir, "AppRun"), 0o755)
    with open(os.path.join(appdir, "character-studio.desktop"), "w", encoding="utf-8") as f:
        f.write(DESKTOP)
    shutil.copy2(os.path.join(HERE, "icon.png"), os.path.join(appdir, "character-studio.png"))
    os.symlink("character-studio.png", os.path.join(appdir, ".DirIcon"))
    image = os.path.join(out, "CharacterStudio-%s-x86_64.AppImage" % ARGS.version)
    if not appimagetool:
        print("no appimagetool given: the app is in %s" % appdir)
        return appdir
    env = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")
    # The runtime the licences describe (appimagetool would otherwise fetch whichever is newest).
    pinned = ["--runtime-file", runtime] if runtime else []
    subprocess.run([appimagetool, "--no-appstream", *pinned, appdir, image], check=True, env=env)
    os.chmod(image, os.stat(image).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return image


def main(argv):
    global ARGS
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--python", required=True, help="a relocatable Python 3.12 for this system")
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--work", help="where to put the app together (default: OUT/work)")
    parser.add_argument("--iscc", help="Inno Setup's compiler (Windows)")
    parser.add_argument("--appimagetool", help="appimagetool (Linux)")
    parser.add_argument("--appimage-runtime", help="the AppImage runtime to use (Linux; the one "
                        "appimage-runtime-licences.txt describes)")
    ARGS = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9][0-9A-Za-z.\-]{0,30}", ARGS.version):
        raise SystemExit("the version should look like 2026.11.21")
    out = os.path.abspath(ARGS.out)
    work = os.path.abspath(ARGS.work or os.path.join(out, "work"))
    if os.path.exists(work):
        shutil.rmtree(work)
    os.makedirs(work)
    os.makedirs(out, exist_ok=True)
    python_dir = os.path.abspath(ARGS.python)
    if sys.platform == "win32":
        made = build_windows(work, out, python_dir, ARGS.iscc)
    elif sys.platform == "darwin":
        made = build_mac(work, out, python_dir)
    else:
        made = build_linux(work, out, python_dir, ARGS.appimagetool, ARGS.appimage_runtime)
    print("made", made)
    return 0


ARGS = None

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
