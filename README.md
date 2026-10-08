# ✨ PLATINE

Widget média minimaliste pour Windows avec fond acrylique et étoile animée.

![Electron](https://img.shields.io/badge/Electron-33-47848F?logo=electron&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-11-0078D4?logo=windows&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

![Aperçu](docs/screenshot.png)

## 🎵 Fonctionnalités

- 🪟 **Fond acrylique** translucide (Fluent Design / Fluent Flyouts)
- ⭐ **Étoile animée** : tourne et pulse au rythme de la lecture
- 🎛️ **Contrôles complets** : lecture/pause, précédent, suivant, position
- 📊 **Visualiseur** intégré dans la barre de progression
- 🔒 **Mode bureau** (derrière les fenêtres) + `Alt+V` pour passer au-dessus
- 🎯 **Pont SMTC** : fonctionne avec tous les lecteurs Windows
  - Spotify Desktop, Apple Music, foobar2000, Deezer, VLC, YouTube Music, etc.
- 🖼️ **Vignettes** natives SMTC avec fallback iTunes
- 🔊 **Volume système** pilotable
- 💾 **Position mémorisée** entre les sessions

## 🚀 Installation

### Mode Release (utilisateur)

1. Téléchargez le dossier `release/` depuis ce dépôt
2. Clic droit sur `installer.ps1` → **Exécuter avec PowerShell**
3. L'installeur crée :
   - `PLATINE.exe` (widget)
   - `PLATINE-Bridge.exe` (pont média)
   - Raccourci bureau + démarrage automatique

### Mode Dev (développeur)

Prérequis : [Node.js](https://nodejs.org), Python 3.11+, Git.

```powershell
# Cloner
git clone https://github.com/spectglak-ui/platine.git
cd platine

# Dépendances
npm install
pip install winsdk websockets pycaw comtypes pyinstaller

# Lancer
powershell -ExecutionPolicy Bypass -File installer.ps1