---
name: video-edit
description: "Pipeline automatizado de pós-produção para YouTube. Sync de áudio, denoise, corte de fillers PT-BR, corte de silêncios, BG removal, motion graphics, SFX, render 16:9 + 9:16 Shorts. Roda 100% local em CPU. Use quando o usuário quiser editar um episódio gravado bruto."
triggers:
  - video edit
  - editar video
  - editar vídeo
  - pós-produção
  - pos producao
  - youtube edit
  - render video
---

# Skill `video-edit`

Pipeline automatizado de pós-produção para vídeos YouTube. Processa episódios brutos e gera `final_16x9.mp4` + `final_9x16_shorts.mp4`.

## Uso

```bash
# Processar episódio completo
python3 .claude/skills/video-edit/scripts/video_edit.py /caminho/episodio/

# Retomar de um estágio específico
python3 .claude/skills/video-edit/scripts/video_edit.py /caminho/episodio/ --resume-from bg-removal

# Preview rápido (5min @ 540p)
python3 .claude/skills/video-edit/scripts/video_edit.py /caminho/episodio/ --preview

# Pular estágios opcionais
python3 .claude/skills/video-edit/scripts/video_edit.py /caminho/episodio/ --skip bg-removal,motion-graphics
```

## Flags

| Flag | Descrição |
|------|-----------|
| `--resume-from STAGE` | Continua do estágio especificado (pula anteriores) |
| `--skip STAGES` | Pula estágios (CSV): `bg-removal,motion-graphics,sfx` |
| `--preview` | Processa só 5min em 540p para validação rápida |
| `--config PATH` | Usa config customizado em vez de `config/defaults.yaml` |
| `--cloud-bg-removal PROVIDER` | Usa GPU cloud para BG removal (runpod\|colab) — v2 |
| `--audio-offset SECONDS` | Força offset de sync (fallback manual) |
| `--verbose` | Logs detalhados |

## Estágios do Pipeline

```
1. sync         → Sincroniza áudio externo com vídeo (clap detection)
2. audio        → DeepFilterNet denoise + EQ + normalize -14 LUFS
3. transcribe   → WhisperX word-level timestamps PT-BR
4. cut-fillers  → Remove fillers PT-BR (≥250ms)
5. cut-silence  → Remove silêncios (>800ms) via auto-editor
6. bg-removal   → MediaPipe segmentation + composite background
7. motion       → Overlay motion graphics (marcadores [graphic:NOME])
8. sfx          → Mix SFX nos marcadores [sfx:NOME]
9. render       → H.264 16:9 + 9:16 Shorts
```

## Estrutura de Diretório do Episódio

```
workspace/projects/youtube/episodes/{slug}/
├── video.mp4              # Vídeo bruto da câmera
├── audio_externo.wav      # Áudio do gravador externo (opcional)
├── instructions.md        # Instruções específicas do episódio (opcional)
├── assets/                # Assets específicos do episódio (opcional)
│
├── # Artefatos gerados pelo pipeline:
├── audio_synced.wav
├── audio_final.wav
├── transcript.json
├── video_no_fillers.mp4
├── video_cut.mp4
├── video_bg_replaced.mp4
├── video_with_graphics.mp4
├── audio_with_sfx.wav
├── final_16x9.mp4         # Output principal
├── final_9x16_shorts.mp4  # Output Shorts/Reels
├── pipeline_state.json    # Estado para resume
└── pipeline.log           # Logs estruturados
```

## Arquivo `instructions.md` (opcional)

Cada episódio pode ter um `instructions.md` com diretivas:

```markdown
# Episode Instructions

## Skip Stages
- bg-removal    # Podcast sem necessidade de trocar fundo
- motion        # Sem motion graphics neste episódio

## Background
bg_image: outro-fundo.png  # Usa imagem alternativa

## Shorts Segments
shorts_segments:
  - start: 00:02:30
    end: 00:03:30
  - start: 00:10:00
    end: 00:11:00

## Custom Thresholds
filler_min_duration: 300ms  # Mais conservador
silence_threshold: 0.05     # Menos agressivo
```

## Assets de Marca

```
.claude/skills/video-edit/
├── assets/
│   ├── studio-bg.png         # Background padrão (1920x1080)
│   ├── sfx/
│   │   ├── whoosh.wav
│   │   ├── pop.wav
│   │   └── transition.wav
│   └── motion-templates/
│       ├── lower-third.html
│       ├── title-card.html
│       └── callout.html
```

Se ausentes, o pipeline gera placeholders e um `README-assets.md`.

## Marcadores no Transcript

O pipeline reconhece marcadores inseridos na transcrição (via edição manual pós-transcribe):

- `[graphic:NOME]` — Insere motion graphic no timestamp
- `[graphic:NOME duration=2.5]` — Com duração customizada
- `[sfx:NOME]` — Insere efeito sonoro no timestamp
- `[shorts:start]` / `[shorts:end]` — Delimita segmento para 9:16

## Requirements

- Python 3.10+
- ffmpeg 4.4+
- ~4GB RAM para WhisperX medium
- ~20GB disco para modelos + artefatos

## Instalação

```bash
bash .claude/skills/video-edit/scripts/install.sh
```

## Verificação

```bash
source .claude/skills/video-edit/.venv/bin/activate
python -c "import whisperx, mediapipe, deepfilternet; print('OK')"
```

## Specs Técnicos

| Parâmetro | Valor |
|-----------|-------|
| LUFS alvo | -14 (YouTube spec) |
| True peak | ≤ -1 dBTP |
| Codec | H.264 yuv420p |
| Resolução 16:9 | 1920x1080 @ 30fps |
| Resolução 9:16 | 1080x1920 @ 30fps |
| Áudio | AAC 192kbps stereo |
| Max shorts duration | 60s |

## Limitações (v1)

- Sem lipsync AI (MuseTalk cloud apenas em v2)
- BG removal CPU pode levar horas em episódios longos
- Motion graphics requer Node.js para HyperFrames
- Sem UI visual / timeline interativa
