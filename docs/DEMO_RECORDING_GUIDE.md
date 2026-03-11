# Demo Recording Guide

Record a 30-45 second GIF for the README. This is the single most important visual for GitHub stars — projects with strong visual READMEs get ~60% more engagement.

## Tools

- **macOS:** [Kap](https://getkap.co/) (free, records GIF directly) or QuickTime + [Gifski](https://gif.ski/)
- **Linux:** [Peek](https://github.com/phw/peek) or OBS + ffmpeg
- **Cross-platform:** OBS Studio → convert with `ffmpeg -i demo.mp4 -vf "fps=15,scale=800:-1" docs/assets/demo.gif`

## Setup Before Recording

1. Start the app: `docker compose up -d --build`
2. Open browser at http://localhost:3001 (use Chrome, 1280x800 window)
3. Clear any existing courses (start fresh)
4. Prepare a sample PDF (2-3 pages, technical content like a CS lecture)
5. Hide browser bookmarks bar and extensions
6. Use a clean dark background

## Recording Script (30-45 seconds)

### Scene 1: Upload (0-8s)
1. Show the clean dashboard/home page (1-2s pause)
2. Click "New Course" or drag-drop a PDF
3. Type course name: "CS101 — Data Structures"
4. Click "Start Learning"

### Scene 2: AI Generates Content (8-18s)
1. Show the ingestion progress (notes being generated)
2. Wait for the workspace to appear with blocks
3. Scroll through AI-generated notes with LaTeX formulas

### Scene 3: Block Workspace (18-30s)
1. Show the block-based workspace (notes, quiz, flashcards visible)
2. Click on a quiz block — answer a question
3. Open the chat drawer — ask the AI tutor a question
4. Show the AI response streaming with source citations

### Scene 4: Closing (30-35s)
1. Zoom out to show the full workspace
2. End with a clean shot of the dashboard

## Recording Settings

- **Resolution:** 1280x800 (or 1440x900)
- **FPS:** 15 (for GIF) or 30 (for MP4)
- **GIF max size:** Under 5MB (GitHub renders inline up to 10MB, but smaller loads faster)
- **Format:** GIF for README, MP4 for Product Hunt/Twitter

## Post-Processing

```bash
# Convert MP4 to optimized GIF
ffmpeg -i demo.mp4 -vf "fps=15,scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" -loop 0 docs/assets/demo.gif

# Check file size
ls -lh docs/assets/demo.gif
```

## After Recording

1. Save as `docs/assets/demo.gif`
2. Uncomment the GIF line in README.md (replace the screenshot reference)
3. Also save an MP4 version for social media posts

## Tips

- Move your mouse deliberately and slowly — fast mouse movements look chaotic in GIFs
- Pause for 1-2 seconds on important screens so viewers can read
- Use a sample PDF with visually interesting content (math formulas, diagrams)
- If the AI response is slow (local LLM), speed up that portion in post-processing
- Add a subtle cursor highlight if your recording tool supports it
