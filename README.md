# AI ATC for X-Plane

An AI-powered Air Traffic Controller for X-Plane 11/12 that uses a hybrid decision-tree + LLM architecture to provide a professional, realistic, and responsive ATC experience. Inspired by [OpenSquawk](https://github.com/OpenSquawk/OpenSquawk).

## Features
- 🌲 **Decision Tree Logic**: Uses a structured graph for every flight phase to ensure zero hallucinations and instant responses for routine calls.
- 🤖 **Gemini 1.5 Flash Integration**: Cloud-based STT and LLM routing for high-accuracy transcription and intelligent intent detection.
- 📻 **Real Radio Effects**: Custom FFmpeg audio pipeline that adds telephone-band filtering, compression, and radio static to make the ATC sound like an actual VHF radio.
- ✅ **Readback Verification**: Actually listens to your readbacks. If you forget your squawk or the assigned runway, the controller will catch it and ask for a correction.
- ⚙️ **System Settings GUI**: Manage your X-Plane folder, SimBrief username, and default callsign directly in the app. Settings persist between sessions.
- 🪟 **Multi-Platform**: Full support for Windows, macOS, and Linux.

## Prerequisites
- **Python 3.9+**
- **X-Plane 11 or 12**
- **Google AI API Key**: Get one for free at [Google AI Studio](https://aistudio.google.com/).
- **FFmpeg & ffplay**: Required for the radio voice effects and playback.
  - **Mac**: `brew install ffmpeg`
  - **Windows**: [Download from gyan.dev](https://www.gyan.dev/ffmpeg/builds/)
  - **Linux**: `sudo apt install ffmpeg`

## Installation
1. **Clone the repository**:
   ```bash
   git clone https://github.com/ZeleOeO/ai_atc.git
   cd ai_atc
   ```

2. **Setup environment**:
   Create a `.env` file in the root directory:
   ```env
   GOOGLE_API_KEY=your_gemini_api_key_here
   ```

3. **Install dependencies**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # Or .venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

## Running
Make sure X-Plane is running, then start the AI ATC:

```bash
# Just run it—you can set your X-Plane path and SimBrief in the GUI
python -m ai_atc.main
```

Upon launching, click **SYSTEM SETTINGS** in the sidebar to configure your X-Plane folder and SimBrief details once.

## Usage
I built this because the default X-Plane ATC is... well, you know. I wanted something that actually listens to what I say and sounds like a real controller. 

## Testing
To run a quick smoke test of the core modules:
```bash
python tests/test_quick.py
```

## Steps to Contribute
Contributions are welcome! If you have ideas for better phraseology or new features, open a PR.
1. Fork the Repo.
2. Keep the code clean—I just spent forever removing all my emojis and messy comments.
3. Make sure your logic fits into the `decision_tree.py` structure.

## About
A simple project aimed at making flight simming a bit more immersive without needing to pay for professional subscriptions or wait for real controllers to come online.
