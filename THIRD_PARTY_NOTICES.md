# Third-party notices

Twitch Drop Farmer is licensed under the PolyForm Noncommercial License 1.0.0 (see `LICENSE`). The Windows
package also contains the software below, each under its own license. Those licenses apply to those
components only, not to Twitch Drop Farmer itself.

| Component | License | Where to find the license text and the source |
| --- | --- | --- |
| Qt 6 and PySide6, including Qt WebEngine (which is based on Chromium) | LGPL-3.0 (they are also offered under GPL and commercial licenses; this program uses them under the LGPL-3.0) | https://www.gnu.org/licenses/lgpl-3.0.html · Qt source: https://code.qt.io · PySide6: https://pypi.org/project/PySide6/ · WebEngine and Chromium notices: https://doc.qt.io/qt-6/qtwebengine-licensing.html |
| requests | Apache-2.0 | https://www.apache.org/licenses/LICENSE-2.0 |
| urllib3 | MIT | https://github.com/urllib3/urllib3/blob/main/LICENSE.txt |
| certifi (Mozilla CA bundle, unmodified) | MPL-2.0 | https://www.mozilla.org/MPL/2.0/ |
| charset-normalizer | MIT | https://github.com/jawah/charset_normalizer/blob/master/LICENSE |
| idna | BSD-3-Clause | https://github.com/kjd/idna/blob/master/LICENSE.md |
| win10toast | BSD (as declared by the package) | https://pypi.org/project/win10toast/ |
| pywin32 / pypiwin32 | PSF License | https://pypi.org/project/pywin32/ |
| Python runtime (`python310.dll` and the standard library) | PSF License | https://docs.python.org/3/license.html |
| PyInstaller (builds the package; its bootloader is part of `TwitchDropFarmer.exe`) | GPL-2.0-or-later with a special exception that allows programs built with it to be distributed under any license | https://pyinstaller.org/en/stable/license.html |
| Microsoft Visual C++ runtime (`VCRUNTIME140*.dll`, `MSVCP140.dll`) | Redistributable under Microsoft's terms | https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files |

## About the Qt libraries

The Qt libraries are shipped as separate DLL files inside the `_internal\PySide6` folder of the package. As the
LGPL requires, you may replace them with another build of the same Qt version. The LGPL covers Qt and PySide6
only; it does not change the license of Twitch Drop Farmer.

## When running from source

If you run Twitch Drop Farmer from the source code, the libraries listed in `requirements.txt` are installed from
PyPI together with their own license files, which stay with them.

This list is given in good faith and is not legal advice.
