"""
AI 영상 제작 시스템
==================
Google Gemini Vision으로 자막을 생성하고 MoviePy로 여행 영상을 자동 제작합니다.

환경 변수 설정:
  Windows PowerShell : $env:GEMINI_API_KEY = "AIza..."
  .env 파일 (같은 폴더): GEMINI_API_KEY=AIza...

실행 방법:
  streamlit run travel.py
"""

# ── 패키지 자동 설치 ──────────────────────────────────────────────────────────
import subprocess
import sys

_REQUIRED = [
    "streamlit>=1.32.0",
    "openai>=1.0.0",
    "moviepy>=1.0.3,<2.0.0",
    "Pillow>=10.2.0",
    "numpy>=1.26.0",
    "imageio>=2.33.0",
    "imageio-ffmpeg>=0.4.9",
    "python-dotenv>=1.0.0",
    "emoji>=2.0.0",
]

def _install_packages():
    try:
        import importlib
        _check = {
            "streamlit": "streamlit", "openai": "openai",
            "moviepy": "moviepy", "PIL": "Pillow",
            "numpy": "numpy", "imageio": "imageio",
            "dotenv": "python-dotenv", "emoji": "emoji",
        }
        missing = [pkg for mod, pkg in _check.items()
                   if importlib.util.find_spec(mod) is None]
        if missing:
            print(f"[자동 설치] 누락 패키지: {missing}")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install"] + _REQUIRED,
                stdout=subprocess.DEVNULL,
            )
            print("[자동 설치] 완료. 앱을 다시 실행해 주세요.")
    except Exception as e:
        print(f"[자동 설치 실패] 직접 설치하세요: pip install -r requirements.txt\n{e}")

_install_packages()
# ─────────────────────────────────────────────────────────────────────────────

import os
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional

# imageio-ffmpeg 번들 바이너리를 moviepy에 등록 (시스템 ffmpeg 없어도 오디오 인코딩 동작)
try:
    import imageio_ffmpeg
    from moviepy.config import change_settings
    change_settings({"FFMPEG_BINARY": imageio_ffmpeg.get_ffmpeg_exe()})
except Exception:
    pass

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import streamlit as st

# .env 파일 지원 (python-dotenv 설치 시 자동 로드)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── 상수 ──────────────────────────────────────────────────────────────────────

SUPPORTED_EXTS    = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
EMOJI_CACHE_DIR   = Path(__file__).resolve().parent / ".emoji_cache"
VIDEO_SIZE        = (1280, 720)
DEFAULT_CLIP_SEC  = 3.0
FADE_SEC          = 0.5
AUDIO_FADEOUT_SEC = 3.0
CAPTION_FONT_SIZE = 40
OPENAI_MODEL      = "gpt-4o-mini"

PRESET_EMOJIS = {
    "여행": ["✈️","🗺️","🏖️","🏝️","⛰️","🌊","🏔️","🚢","🚗","🚂","🗼","🏯","⛩️","🏰","🌁","🛫","🛬","🧳"],
    "자연": ["🌸","🌺","🌻","🌹","🍀","🌿","🌾","🍃","🌲","🌳","🌴","🌵","🌼","🪷","🌱","🍂","🍁"],
    "날씨/하늘": ["☀️","🌤️","⛅","🌈","🌙","⭐","✨","💫","🌟","❄️","🌅","🌄","🌇","🌆","🌃","🌉","🎑"],
    "음식": ["🍣","🍜","🍕","🍔","🍦","🍰","🎂","🥗","🍱","🥘","🍷","☕","🧋","🍺","🥂","🍾","🧁"],
    "감정/하트": ["😊","😍","🥰","💕","💖","💗","💝","❤️","🧡","💛","💚","💙","💜","🤍","🫶","😎","🥹"],
    "축하/활동": ["🎉","🎊","🎈","🎁","🎵","🎶","🥂","🎆","🎇","🎠","🎡","🎢","🎪","🎭","🎬","🎤"],
    "가족/사람": ["👨‍👩‍👧‍👦","👨‍👩‍👧","👨‍👩‍👦","👪","🤗","🤝","👋","🙌","💪","🫂","👶","🧒","👧","👦"],
    "기타": ["🌴","🏞️","🗻","🌋","🏕️","⛺","🪨","🌠","🎑","🏟️","🎠","🛶","⛵","🚁","🪂"],
}

CAPTION_SYSTEM_PROMPT = (
    "여행 영상 자막 전문가. 사진을 보고 한 줄 자막만 출력. "
    "줄바꿈·따옴표·번호·설명 절대 금지."
)

CAPTION_STYLES = {
    "1. 인스타그램 인플루언서": "SNS 인플루언서 톤. 사진 분위기를 감성적·서정적으로. 20자 내외. 이모지 1~2개. 따뜻한 반말.",
    "2. 카피라이터/유머": "감성 카피라이터 톤. 피식 웃음+묘한 감동. 따뜻한 해석·과장. 다정하게 툭 던지는 말투.",
    "3. 감성 브이로그": "가족 여행 브이로그 톤. 단어·짧은 구절로 여운과 따뜻함. 명사형 종결. 예: '바람, 햇살, 완벽했던 오후'",
    "4. 숏폼 여행 인플루언서": "여행 인플루언서 톤. 15자 이내. 따뜻한 해석·위트. 다정한 반말. 이모지 1개.",
}

KOREAN_FONT_PATHS = [
    r"C:\Windows\Fonts\malgun.ttf",       # 맑은 고딕 (Windows 기본)
    r"C:\Windows\Fonts\malgunbd.ttf",     # 맑은 고딕 Bold
    r"C:\Windows\Fonts\NanumGothic.ttf",
    r"C:\Windows\Fonts\gulim.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",                  # macOS
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",             # Linux (fonts-nanum)
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",      # Linux (noto-cjk)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


# ── 이미지 유틸리티 ────────────────────────────────────────────────────────────

def get_font(size: int = CAPTION_FONT_SIZE) -> ImageFont.FreeTypeFont:
    """한국어 지원 TrueType 폰트 반환 (없으면 PIL 기본 폰트)"""
    for path in KOREAN_FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


_EMOJI_IMG_CACHE: dict = {}


def _split_emoji(text: str) -> list:
    """텍스트를 [(is_emoji, segment), ...] 로 분리."""
    try:
        import emoji as _e
        items = _e.emoji_list(text)
        if not items:
            return [(False, text)]
        result, last = [], 0
        for item in items:
            s, e = item["match_start"], item["match_end"]
            if s > last:
                result.append((False, text[last:s]))
            result.append((True, item["emoji"]))
            last = e
        if last < len(text):
            result.append((False, text[last:]))
        return result
    except Exception:
        return [(False, text)]


def _emoji_codepoint(emoji_str: str) -> str:
    """이모지 → twemoji URL 코드포인트 문자열 (변형선택자 U+FE0F·U+FE0E 제거)."""
    return "-".join(
        f"{ord(c):x}" for c in emoji_str if ord(c) not in (0xFE0F, 0xFE0E)
    )


def _fetch_twemoji_png(cp: str) -> Optional[Image.Image]:
    """로컬 캐시 → CDN 순으로 Twemoji PNG 반환. 다운로드 성공 시 로컬 저장."""
    from io import BytesIO as _BytesIO

    EMOJI_CACHE_DIR.mkdir(exist_ok=True)
    cache_file = EMOJI_CACHE_DIR / f"{cp}.png"

    if cache_file.exists():
        try:
            return Image.open(cache_file).convert("RGBA")
        except Exception:
            cache_file.unlink(missing_ok=True)

    candidates = [
        f"https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{cp}.png",
        f"https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{cp}-fe0f.png",
        f"https://abs-0.twimg.com/emoji/v2/72x72/{cp}.png",
    ]
    for url in candidates:
        try:
            try:
                import requests as _req
                r = _req.get(url, timeout=5)
                if r.status_code == 200:
                    img = Image.open(_BytesIO(r.content)).convert("RGBA")
                    img.save(cache_file)
                    return img
            except ImportError:
                import urllib.request
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = resp.read()
                img = Image.open(_BytesIO(data)).convert("RGBA")
                img.save(cache_file)
                return img
        except Exception:
            continue
    return None



def _render_emoji_img(seg: str, size: int) -> Optional[Image.Image]:
    """이모지 이미지 렌더링: 로컬캐시/CDN → 크기 조정 → 없으면 None(생략)."""
    key = (seg, size)
    if key in _EMOJI_IMG_CACHE:
        return _EMOJI_IMG_CACHE[key]

    cp  = _emoji_codepoint(seg)
    raw = _fetch_twemoji_png(cp)
    result = None

    if raw:
        bbox = raw.getbbox()
        if bbox:
            cropped = raw.crop(bbox)
            if cropped.height > 0:
                scale  = size / cropped.height
                w      = max(1, int(cropped.width * scale))
                result = cropped.resize((w, size), Image.LANCZOS)

    _EMOJI_IMG_CACHE[key] = result
    return result


def _text_width(draw: ImageDraw.Draw, text: str, font: ImageFont.FreeTypeFont) -> int:
    """이모지 인식 텍스트 너비 측정."""
    total = 0
    for is_emoji, seg in _split_emoji(text):
        if is_emoji:
            em = _render_emoji_img(seg, font.size)
            if em:
                total += em.width + 2
            else:
                w = draw.textbbox((0, 0), seg, font=font)[2]
                total += w if w > 2 else font.size // 2
        else:
            total += draw.textbbox((0, 0), seg, font=font)[2]
    return total


def _draw_text_line(image: Image.Image, draw: ImageDraw.Draw, text: str,
                    x: int, y: int, font: ImageFont.FreeTypeFont,
                    fill: tuple, color_emoji: bool = True) -> None:
    """이모지 PNG 합성 + 일반 텍스트 렌더링 (세그먼트 단위)."""
    cx = x
    for is_emoji, seg in _split_emoji(text):
        if is_emoji:
            em = _render_emoji_img(seg, font.size)
            if em:
                if color_emoji:
                    image.paste(em, (cx, y), em)
                cx += em.width + 2
            # else: 렌더링 실패 시 이모지 생략
        else:
            draw.text((cx, y), seg, font=font, fill=fill)
            cx += draw.textbbox((0, 0), seg, font=font)[2]


def letterbox(img: Image.Image, size: tuple = VIDEO_SIZE) -> Image.Image:
    """종횡비를 유지하며 검은 패딩으로 지정 크기에 맞춤"""
    rgb = img.convert("RGB")
    rgb.thumbnail(size, Image.LANCZOS)
    canvas = Image.new("RGB", size, (0, 0, 0))
    canvas.paste(rgb, ((size[0] - rgb.width) // 2, (size[1] - rgb.height) // 2))
    return canvas


def wrap_text(text: str, font: ImageFont.FreeTypeFont,
              max_px: int, draw: ImageDraw.Draw) -> list:
    """텍스트를 max_px 픽셀 이하로 줄 바꿈 (이모지 인식)"""
    words, lines, buf = text.split(), [], ""
    for word in words:
        trial = (buf + " " + word).strip()
        w = _text_width(draw, trial, font)
        if w <= max_px:
            buf = trial
        else:
            if buf:
                lines.append(buf)
            buf = word
    if buf:
        lines.append(buf)
    return lines or [text]


def stamp_caption(img: Image.Image, caption: str,
                  font: ImageFont.FreeTypeFont) -> np.ndarray:
    """자막 합성 (이모지 지원, pilmoji 미사용) → uint8 RGB ndarray 반환"""
    base = img.convert("RGBA")

    tmp_draw = ImageDraw.Draw(base)
    lines = wrap_text(caption, font, base.width - 80, tmp_draw)

    lh  = CAPTION_FONT_SIZE + 8
    th  = len(lines) * lh
    pad = 18

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    y0 = base.height - th - pad * 2
    od.rectangle([0, y0, base.width, base.height], fill=(0, 0, 0, 150))
    base = Image.alpha_composite(base, overlay)

    draw = ImageDraw.Draw(base)
    for i, line in enumerate(lines):
        w = _text_width(draw, line, font)
        x = (base.width - w) // 2
        y = y0 + pad + i * lh
        for dx, dy in [(-2,-2),(-2,0),(-2,2),(0,-2),(0,2),(2,-2),(2,0),(2,2)]:
            _draw_text_line(base, draw, line, x+dx, y+dy, font, (0, 0, 0, 255), color_emoji=False)
        _draw_text_line(base, draw, line, x, y, font, (255, 255, 255, 255), color_emoji=True)

    return np.array(base.convert("RGB"))


# ── AI 자막 생성 ───────────────────────────────────────────────────────────────

def generate_caption(img_path: str, api_key: str, style: str = "3. 감성 브이로그") -> tuple:
    """Gemini Vision으로 한국어 여행 자막 생성 → (caption, prompt_tokens, completion_tokens)"""
    import base64
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    prompt = CAPTION_STYLES.get(style, CAPTION_STYLES["3. 감성 브이로그"])

    buf = BytesIO()
    Image.open(img_path).convert("RGB").save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": CAPTION_SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"}},
                ]},
            ],
            max_tokens=60,
        )
        text  = response.choices[0].message.content.strip().strip("\"'")
        text  = text if text else "아름다운 순간이 영원히 기억에 남다."
        usage = response.usage
        return text, usage.prompt_tokens, usage.completion_tokens
    except Exception as e:
        raise RuntimeError(f"OpenAI API 호출 실패: {e}") from e


def polish_caption(raw: str, api_key: str) -> str:
    """사용자 자막을 AI로 다듬고 이모지 추가 → 개선된 자막 반환."""
    from openai import OpenAI
    if not raw.strip():
        return raw
    client = OpenAI(api_key=api_key)
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "여행 영상 자막 다듬기 전문가. 한 줄 자막만 출력. 따옴표·설명 금지."},
                {"role": "user", "content": f"감성적으로 다듬고 이모지 1~2개 추가. 길이 유지.\n원문: {raw}"},
            ],
            max_tokens=60,
        )
        result = response.choices[0].message.content.strip().strip("\"'")
        return result if result else raw
    except Exception:
        return raw


def _trigger_polish():
    st.session_state["_do_polish"] = True


# ── 영상 제작 ─────────────────────────────────────────────────────────────────

def build_slideshow(
    paths: list,
    captions: list,
    clip_sec: float,
    rotations: list = None,
    on_progress: Optional[Callable] = None,
) -> str:
    """이미지+자막으로 슬라이드쇼 MP4 제작 (오디오 없음) → 임시 파일 경로"""
    from moviepy.editor import ImageClip, concatenate_videoclips

    font  = get_font()
    clips = []

    for i, (path, caption) in enumerate(zip(paths, captions)):
        if on_progress:
            on_progress(i / len(paths))

        with Image.open(path) as raw:
            if rotations and rotations[i]:
                raw = raw.rotate(-rotations[i], expand=True)
            framed = letterbox(raw)

        arr  = stamp_caption(framed, caption, font)
        clip = ImageClip(arr, duration=clip_sec)

        # 첫 번째 사진은 fadein, 이후는 crossfadein으로 부드럽게 전환
        if i == 0:
            clip = clip.fadein(FADE_SEC)
        else:
            clip = clip.crossfadein(FADE_SEC)

        # 마지막 사진만 fadeout
        if i == len(paths) - 1:
            clip = clip.fadeout(FADE_SEC)

        clips.append(clip)

    # crossfade 적용 시 padding=-FADE_SEC 으로 클립이 겹치며 전환
    merged = concatenate_videoclips(clips, method="compose", padding=-FADE_SEC)
    out    = tempfile.NamedTemporaryFile(suffix="_slide.mp4", delete=False).name
    merged.write_videofile(
        out, fps=24, codec="libx264", audio=False,
        verbose=False, logger=None,
    )
    for c in clips:
        c.close()
    merged.close()

    if on_progress:
        on_progress(1.0)
    return out


def add_music(video_path: str, audio_path: str,
              audio_start: float = 0.0, audio_end: float = 0.0) -> str:
    """배경음악 트리밍 + 루프 + 페이드아웃 합성 → 최종 MP4 경로 (ffmpeg 직접 호출)"""
    import subprocess
    import imageio_ffmpeg as _iff

    ffmpeg = _iff.get_ffmpeg_exe()

    # 영상 길이 확인
    probe = subprocess.run(
        [ffmpeg, "-i", video_path],
        capture_output=True, text=True,
    )
    vdur = None
    for line in probe.stderr.splitlines():
        if "Duration:" in line:
            ts = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = ts.split(":")
            vdur = float(h) * 3600 + float(m) * 60 + float(s)
            break
    if not vdur:
        raise RuntimeError(f"영상 길이를 읽을 수 없습니다.\nffmpeg 출력:\n{probe.stderr[-800:]}")

    # 구간 트리밍: start/end가 지정된 경우 먼저 해당 구간만 추출
    trimmed_audio: Optional[str] = None
    src_audio = audio_path
    if audio_start > 0 or audio_end > 0:
        trimmed_audio = tempfile.NamedTemporaryFile(suffix=".aac", delete=False).name
        trim_cmd = [ffmpeg, "-y"]
        if audio_start > 0:
            trim_cmd += ["-ss", f"{audio_start:.3f}"]
        trim_cmd += ["-i", audio_path]
        if audio_end > 0:
            seg_dur = audio_end - audio_start
            trim_cmd += ["-t", f"{seg_dur:.3f}"]
        trim_cmd += ["-c:a", "aac", "-b:a", "192k", trimmed_audio]
        tr = subprocess.run(trim_cmd, capture_output=True, text=True)
        if tr.returncode != 0:
            raise RuntimeError(f"음악 구간 추출 실패 (code {tr.returncode}):\n{tr.stderr[-800:]}")
        src_audio = trimmed_audio

    fade_start = max(0.0, vdur - AUDIO_FADEOUT_SEC)
    out = tempfile.NamedTemporaryFile(suffix="_final.mp4", delete=False).name

    try:
        result = subprocess.run(
            [
                ffmpeg, "-y",
                "-i", video_path,
                "-stream_loop", "-1", "-i", src_audio,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-af", f"afade=t=out:st={fade_start:.3f}:d={min(AUDIO_FADEOUT_SEC, vdur):.3f}",
                "-t", f"{vdur:.3f}",
                out,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 오디오 합성 실패 (code {result.returncode}):\n{result.stderr[-1200:]}")
    finally:
        if trimmed_audio and os.path.exists(trimmed_audio):
            try:
                os.unlink(trimmed_audio)
            except OSError:
                pass

    return out


def compress_video(input_path: str, crf: int = 28, max_height: int = 0) -> str:
    """ffmpeg H.264 CRF 압축 → 임시 MP4 경로 반환"""
    import imageio_ffmpeg as _iff
    ffmpeg = _iff.get_ffmpeg_exe()
    out = tempfile.NamedTemporaryFile(suffix="_compressed.mp4", delete=False).name
    cmd = [ffmpeg, "-y", "-i", input_path,
           "-c:v", "libx264", "-crf", str(crf), "-preset", "fast"]
    if max_height > 0:
        cmd += ["-vf", f"scale=-2:{max_height}"]
    cmd += ["-c:a", "aac", "-b:a", "128k", out]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"압축 실패 (code {result.returncode}):\n{result.stderr[-800:]}")
    return out


# ── 비밀번호 인증 ─────────────────────────────────────────────────────────────

def require_password():
    """secrets.toml에 APP_PASSWORD가 설정된 경우 로그인 게이트를 표시.
    인증 전이면 st.stop()으로 이후 코드를 차단한다."""
    correct = _get_secret("APP_PASSWORD")
    if not correct:
        return  # 비밀번호 미설정 시 게이트 없이 통과

    if st.session_state.get("authenticated"):
        return

    st.title("🔒 AI 영상 제작 시스템")
    pwd = st.text_input("비밀번호를 입력하세요", type="password", key="pwd_input")
    if st.button("로그인", type="primary"):
        if pwd == correct:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")
    st.stop()


# ── 시크릿 로더 ───────────────────────────────────────────────────────────────

def _load_secrets_file() -> dict:
    """스크립트 위치 기준 .streamlit/secrets.toml 직접 파싱 (CWD 불일치 대비)"""
    try:
        import tomllib
    except ImportError:
        return {}
    p = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    if not p.exists():
        return {}
    try:
        with open(p, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _get_secret(key: str) -> str:
    """st.secrets → secrets.toml 직접 읽기 → 환경변수 순으로 조회"""
    try:
        return st.secrets[key]
    except Exception:
        pass
    val = _load_secrets_file().get(key, "")
    if val:
        return str(val)
    return os.environ.get(key, "")


def get_api_key() -> str:
    return _get_secret("OPENAI_API_KEY")


# ── 파일 헬퍼 ─────────────────────────────────────────────────────────────────

def scan_folder(folder: str) -> list:
    p = Path(folder)
    if not p.is_dir():
        raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {folder}")
    imgs = sorted(str(f) for f in p.iterdir() if f.suffix.lower() in SUPPORTED_EXTS)
    if not imgs:
        raise ValueError("지원 이미지 파일(jpg/png/webp/bmp)이 없습니다.")
    return imgs


def dump_uploads(files) -> tuple:
    """업로드 파일을 임시 디렉토리에 저장 → (tmp_dir, [paths])"""
    d     = tempfile.mkdtemp()
    paths = []
    for f in files:
        dest = os.path.join(d, f.name)
        with open(dest, "wb") as fp:
            fp.write(f.getbuffer())
        paths.append(dest)
    return d, paths


# ── 폴더 선택 다이얼로그 ──────────────────────────────────────────────────────

def _open_folder_dialog():
    """tkinter 네이티브 폴더 선택창 → 선택 경로를 session_state에 저장."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        folder = filedialog.askdirectory(title="사진 폴더 선택")
        root.destroy()
        if folder:
            st.session_state["folder_input"] = folder
    except Exception:
        pass


# ── 회전 콜백 ─────────────────────────────────────────────────────────────────

def _do_rotate(rot_key: str):
    """렌더 전에 실행되는 on_click 콜백 — 해당 사진 회전값만 90° 증가."""
    st.session_state[rot_key] = (st.session_state.get(rot_key, 0) + 90) % 360


def _trigger_regen_one(i: int):
    st.session_state["_do_regen_one"] = i


def _trigger_polish_one(i: int):
    st.session_state["_do_polish_one"] = i


def _download_emoji_batch(emojis: list) -> tuple:
    """이모지 목록을 로컬 캐시에 다운로드. (성공수, 실패수) 반환."""
    ok = fail = 0
    for em in emojis:
        cp = _emoji_codepoint(em)
        if not cp:
            continue
        cache_file = EMOJI_CACHE_DIR / f"{cp}.png"
        if cache_file.exists():
            ok += 1
            continue
        result = _fetch_twemoji_png(cp)
        if result:
            ok += 1
        else:
            fail += 1
    return ok, fail


def _delete_upload_photo(orig_pos: int):
    order = st.session_state.get("_order_indices", [])
    st.session_state["_order_indices"] = [i for i in order if i != orig_pos]


def _delete_folder_photo(orig_pos: int):
    order = st.session_state.get("_folder_order_indices", [])
    st.session_state["_folder_order_indices"] = [i for i in order if i != orig_pos]


def _move_photo(state_key: str, orig_pos: int, direction: int):
    """사진을 순서 목록에서 direction(−1=앞, +1=뒤)만큼 이동."""
    order = list(st.session_state.get(state_key, []))
    try:
        idx = order.index(orig_pos)
    except ValueError:
        return
    new_idx = idx + direction
    if 0 <= new_idx < len(order):
        order[idx], order[new_idx] = order[new_idx], order[idx]
        st.session_state[state_key] = order


# ── Streamlit UI ──────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="AI 영상 제작 시스템",
        page_icon="🎬",
        layout="wide",
    )

    require_password()

    col_ttl, col_credit = st.columns([8, 1])
    with col_ttl:
        st.title("🎬 AI 영상 제작 시스템")
        st.caption(
            "Google Gemini가 감성 자막을 생성하고, "
            "배경음악이 깔린 여행 영상을 자동으로 만들어 드립니다."
        )
    with col_credit:
        st.markdown(
            "<div style='text-align:right; color:#888; font-size:0.75rem; padding-top:1.2rem;'>"
            "made by<br><b>s.y.Kim</b></div>",
            unsafe_allow_html=True,
        )

    # ── 사이드바 ──────────────────────────────────────────────
    api_key = get_api_key()
    with st.sidebar:
        st.header("⚙️ 설정")
        if not api_key:
            st.error("❌ OPENAI_API_KEY가 설정되지 않았습니다.\n\n`.streamlit/secrets.toml`을 확인하세요.")
        clip_sec = st.slider("사진당 재생 시간 (초)", 2.0, 6.0, DEFAULT_CLIP_SEC, 0.5)

        st.markdown("**📝 자막 방식**")
        caption_mode = st.radio(
            "자막 방식",
            ["🤖 AI 자막 생성", "✏️ 직접 입력"],
            index=0,
            label_visibility="collapsed",
        )

        if caption_mode == "🤖 AI 자막 생성":
            st.markdown("**✍️ 자막 스타일**")
            caption_style = st.radio(
                "자막 스타일",
                options=list(CAPTION_STYLES.keys()),
                index=2,
                label_visibility="collapsed",
                key="caption_style_radio",
            )
        else:
            caption_style = list(CAPTION_STYLES.keys())[2]

        st.divider()
        with st.expander("🎨 이모지 관리"):
            EMOJI_CACHE_DIR.mkdir(exist_ok=True)
            cached = list(EMOJI_CACHE_DIR.glob("*.png"))
            st.caption(f"저장된 이모지: **{len(cached)}개**")

            st.markdown("**카테고리 팩 다운로드**")
            selected_cat = st.selectbox(
                "카테고리",
                ["전체"] + list(PRESET_EMOJIS.keys()),
                key="emoji_cat_select",
                label_visibility="collapsed",
            )
            if st.button("📥 다운로드", key="emoji_dl_btn", use_container_width=True):
                emojis = (
                    [e for lst in PRESET_EMOJIS.values() for e in lst]
                    if selected_cat == "전체"
                    else PRESET_EMOJIS[selected_cat]
                )
                with st.spinner(f"다운로드 중... (0/{len(emojis)})"):
                    ok, fail = _download_emoji_batch(emojis)
                st.success(f"✅ 완료 — 성공 {ok}개" + (f", 실패 {fail}개" if fail else ""))
                st.rerun()

            st.markdown("**이모지 직접 추가**")
            custom_input = st.text_input(
                "이모지 입력",
                placeholder="예: 😎 🌊 ✨",
                key="emoji_custom_input",
                label_visibility="collapsed",
            )
            if st.button("➕ 추가", key="emoji_add_btn", use_container_width=True):
                if custom_input.strip():
                    emojis = list(custom_input.strip())
                    with st.spinner("다운로드 중..."):
                        ok, fail = _download_emoji_batch(emojis)
                    st.success(f"✅ 완료 — 성공 {ok}개" + (f", 실패 {fail}개" if fail else ""))
                    st.rerun()

        with st.expander("💡 사용 방법"):
            st.markdown("""
            **사용 순서**
            1. 사진 업로드 또는 폴더 경로 입력
            2. 배경음악 업로드 *(선택)*
            3. **AI자막 생성 / 직접 입력** 클릭
            4. **AI자막 수정** 클릭
            5. MP4 다운로드 클릭
               OR 영상 확인 후 자막 수정 확인 후
               영상 다시 제작하기 클릭

            **AI 사용량** *(gpt-4o-mini 기준)*
            - 자막 생성&수정 시 토큰 사용
            - 이모지는 전체 **다운로드** 로 속도 향상
            """)

    # ── 사진 입력 ──────────────────────────────────────────────
    col_imgs, col_audio = st.columns([3, 2])

    with col_imgs:
        st.subheader("📸 사진")
        t_upload, t_folder = st.tabs(["📂 파일 업로드", "🗂️ 폴더 경로"])

        with t_upload:
            up_imgs = st.file_uploader(
                "이미지 파일을 드래그하거나 클릭해 업로드하세요 (복수 선택 가능)",
                type=["jpg", "jpeg", "png", "webp", "bmp"],
                accept_multiple_files=True,
                key="img_upload",
            )
            if up_imgs:
                st.success(f"✅ {len(up_imgs)}장 업로드됨")

                # 순서 조정 UI
                st.markdown("**📋 사진 순서 조정** — 번호를 바꿔 순서를 변경하세요")

                # session_state에 순서 초기화 (업로드 목록이 바뀌면 리셋)
                upload_names = [f.name for f in up_imgs]
                if st.session_state.get("_order_names") != upload_names:
                    st.session_state["_order_names"] = upload_names
                    st.session_state["_order_indices"] = list(range(len(up_imgs)))
                    for _k in range(len(up_imgs)):
                        st.session_state[f"_rot_up_{_k}"] = 0

                order = st.session_state["_order_indices"]

                # 사진 미리보기 + 이동·회전·삭제 (2열 그리드)
                n_cols = 2
                n_active = len(order)

                for row_start in range(0, n_active, n_cols):
                    cols = st.columns(n_cols)
                    for ci in range(n_cols):
                        ai = row_start + ci
                        if ai >= n_active:
                            break
                        orig_pos = order[ai]
                        with cols[ci]:
                            _rot_key = f"_rot_up_{orig_pos}"
                            if _rot_key not in st.session_state:
                                st.session_state[_rot_key] = 0
                            _rot = st.session_state[_rot_key]
                            _buf = BytesIO(up_imgs[orig_pos].getbuffer())
                            _img = Image.open(_buf)
                            if _rot:
                                _img = _img.rotate(-_rot, expand=True)
                            st.image(_img, use_container_width=True)
                            _b1, _b2, _b3, _b4 = st.columns(4)
                            with _b1:
                                st.button("◀", key=f"mv_l_up_{orig_pos}",
                                          help="앞으로 이동",
                                          disabled=(ai == 0),
                                          on_click=_move_photo,
                                          args=("_order_indices", orig_pos, -1))
                            with _b2:
                                st.button("▶", key=f"mv_r_up_{orig_pos}",
                                          help="뒤로 이동",
                                          disabled=(ai == n_active - 1),
                                          on_click=_move_photo,
                                          args=("_order_indices", orig_pos, 1))
                            with _b3:
                                st.button("↻", key=f"rot_btn_up_{orig_pos}",
                                          help="90° 회전",
                                          on_click=_do_rotate, args=(_rot_key,))
                            with _b4:
                                st.button("🗑", key=f"del_btn_up_{orig_pos}",
                                          help="삭제",
                                          on_click=_delete_upload_photo, args=(orig_pos,))

                # 콜백이 순서를 직접 관리하므로 session_state 그대로 사용
                active_order = st.session_state["_order_indices"]
                sorted_imgs = [up_imgs[i] for i in active_order]
                st.caption("현재 영상 순서: " + " → ".join(
                    str(active_order[i] + 1) for i in range(len(active_order))
                ))

                # 파이프라인에서 사용할 정렬된 목록을 session_state에 저장
                st.session_state["_sorted_imgs"] = sorted_imgs

        with t_folder:
            _fc1, _fc2 = st.columns([4, 1])
            with _fc1:
                folder_input = st.text_input(
                    "폴더 경로",
                    placeholder=r"예: D:\Travel\Photos",
                    key="folder_input",
                )
            with _fc2:
                st.write("")
                st.button("📂 찾아보기", on_click=_open_folder_dialog, use_container_width=True)
            if st.button("📁 폴더 스캔"):
                if folder_input:
                    try:
                        found = scan_folder(folder_input)
                        st.session_state["folder_image_paths"] = found
                        st.success(f"✅ {len(found)}장 발견")
                    except (FileNotFoundError, ValueError) as e:
                        st.error(str(e))
                        st.session_state.pop("folder_image_paths", None)
                else:
                    st.warning("폴더 경로를 입력해 주세요.")

            if "folder_image_paths" in st.session_state:
                folder_paths = st.session_state["folder_image_paths"]
                st.success(f"✅ {len(folder_paths)}장 준비됨")

                # 순서 조정 UI (업로드 탭과 동일한 방식)
                st.markdown("**📋 사진 순서 조정** — 번호를 바꿔 순서를 변경하세요")

                if st.session_state.get("_folder_order_paths") != folder_paths:
                    st.session_state["_folder_order_paths"] = folder_paths
                    st.session_state["_folder_order_indices"] = list(range(len(folder_paths)))
                    for _k in range(len(folder_paths)):
                        st.session_state[f"_rot_folder_{_k}"] = 0

                order = st.session_state["_folder_order_indices"]
                n_factive = len(order)

                n_cols = 2
                for row_start in range(0, n_factive, n_cols):
                    cols = st.columns(n_cols)
                    for ci in range(n_cols):
                        ai = row_start + ci
                        if ai >= n_factive:
                            break
                        orig_pos = order[ai]
                        with cols[ci]:
                            _frot_key = f"_rot_folder_{orig_pos}"
                            if _frot_key not in st.session_state:
                                st.session_state[_frot_key] = 0
                            _frot = st.session_state[_frot_key]
                            _fpath = folder_paths[orig_pos]
                            _fimg = Image.open(_fpath)
                            if _frot:
                                _fimg = _fimg.rotate(-_frot, expand=True)
                            st.image(_fimg, use_container_width=True)
                            st.caption(Path(_fpath).name)
                            _fb1, _fb2, _fb3, _fb4 = st.columns(4)
                            with _fb1:
                                st.button("◀", key=f"mv_l_f_{orig_pos}",
                                          help="앞으로 이동",
                                          disabled=(ai == 0),
                                          on_click=_move_photo,
                                          args=("_folder_order_indices", orig_pos, -1))
                            with _fb2:
                                st.button("▶", key=f"mv_r_f_{orig_pos}",
                                          help="뒤로 이동",
                                          disabled=(ai == n_factive - 1),
                                          on_click=_move_photo,
                                          args=("_folder_order_indices", orig_pos, 1))
                            with _fb3:
                                st.button("↻", key=f"rot_btn_folder_{orig_pos}",
                                          help="90° 회전",
                                          on_click=_do_rotate, args=(_frot_key,))
                            with _fb4:
                                st.button("🗑", key=f"del_btn_folder_{orig_pos}",
                                          help="삭제",
                                          on_click=_delete_folder_photo, args=(orig_pos,))

                active_folder_order = st.session_state["_folder_order_indices"]
                st.session_state["_sorted_folder_paths"] = [folder_paths[i] for i in active_folder_order]

                st.caption("현재 영상 순서: " + " → ".join(
                    Path(p).name for p in st.session_state["_sorted_folder_paths"]
                ))

    # ── 음악 입력 ──────────────────────────────────────────────
    with col_audio:
        st.subheader("🎵 배경음악")
        up_audio = st.file_uploader(
            "MP3 또는 WAV 업로드",
            type=["mp3", "wav"],
            key="audio_upload",
        )
        if up_audio:
            st.audio(up_audio)
            st.caption("✂️ 사용할 구간 (초)")
            _ac1, _ac2 = st.columns(2)
            audio_start = _ac1.number_input(
                "시작", min_value=0.0, value=0.0, step=1.0,
                key="audio_start", label_visibility="collapsed",
                help="시작 시간 (초)",
            )
            audio_end = _ac2.number_input(
                "종료", min_value=0.0, value=0.0, step=1.0,
                key="audio_end", label_visibility="collapsed",
                help="종료 시간 (초) — 0이면 끝까지",
            )
            if audio_start > 0 or audio_end > 0:
                if audio_end > 0 and audio_end <= audio_start:
                    st.warning("종료 시간은 시작 시간보다 커야 합니다.")
                else:
                    end_label = f"{audio_end:.0f}초" if audio_end > 0 else "끝"
                    st.caption(f"→ {audio_start:.0f}초 ~ {end_label} 구간 사용")
        else:
            audio_start = 0.0
            audio_end   = 0.0
            st.info("업로드하지 않으면 무음 영상으로 제작됩니다.")

    # ── 제작 버튼 ──────────────────────────────────────────────
    st.divider()

    has_images = bool(up_imgs) or ("folder_image_paths" in st.session_state)

    use_ai = (caption_mode == "🤖 AI 자막 생성")
    btn_label = "🤖 AI 자막 생성하기" if use_ai else "✏️ 직접 자막 입력하기"

    if st.button(
        btn_label,
        type="primary",
        use_container_width=True,
        disabled=not has_images,
    ):
        if use_ai and not api_key:
            st.error("❌ GEMINI_API_KEY가 설정되지 않았습니다.")
        else:
            if up_imgs:
                effective_imgs = st.session_state.get("_sorted_imgs") or up_imgs
                _ord = st.session_state.get("_order_indices", list(range(len(up_imgs))))
                effective_rotations = [st.session_state.get(f"_rot_up_{i}", 0) for i in _ord]
            else:
                effective_imgs = st.session_state.get("_sorted_folder_paths") or st.session_state.get("folder_image_paths", [])
                _ford = st.session_state.get("_folder_order_indices", list(range(len(effective_imgs))))
                effective_rotations = [st.session_state.get(f"_rot_folder_{i}", 0) for i in _ford]
            _pipeline_stage1(effective_imgs, up_audio, api_key, clip_sec, caption_style, effective_rotations,
                             use_ai=use_ai,
                             audio_start=st.session_state.get("audio_start", 0.0),
                             audio_end=st.session_state.get("audio_end", 0.0))

    # ── 자막 편집 UI (stage1 완료 후 표시) ───────────────────
    if st.session_state.get("_pp_stage") == "editing":
        st.divider()

        # 완성된 영상 미리보기 (재제작 후 유지)
        if "_pp_video_bytes" in st.session_state:
            st.subheader("🎬 완성된 영상")
            st.video(st.session_state["_pp_video_bytes"])
            _fname = st.session_state.get("_pp_video_filename", "video.mp4")
            st.download_button(
                f"⬇️ MP4 다운로드 ({_fname})",
                data=st.session_state["_pp_video_bytes"],
                file_name=_fname,
                mime="video/mp4",
                use_container_width=True,
                type="primary",
                key="main_video_download",
            )
            st.divider()

        st.subheader("✍️ 자막 수정")

        image_paths = st.session_state.get("_pp_image_paths", [])
        captions    = st.session_state.get("_pp_captions", [])
        rotations   = st.session_state.get("_pp_rotations") or []
        n_caps      = len(image_paths)

        # ── 플래그 처리: text_area 렌더링 전에 실행 ──────────
        _style = st.session_state.get("caption_style_radio", list(CAPTION_STYLES.keys())[2])

        if st.session_state.pop("_do_polish", False):
            with st.spinner("✨ 전체 자막 다듬는 중..."):
                for i in range(n_caps):
                    raw = st.session_state.get(f"_cap_edit_{i}", "")
                    st.session_state[f"_cap_edit_{i}"] = polish_caption(raw, api_key)

        _regen_i = st.session_state.pop("_do_regen_one", None)
        if _regen_i is not None:
            with st.spinner(f"🤖 {_regen_i + 1}번 자막 생성 중..."):
                try:
                    cap, _, _ = generate_caption(image_paths[_regen_i], api_key, _style)
                    st.session_state[f"_cap_edit_{_regen_i}"] = cap
                except Exception as e:
                    st.error(f"❌ {e}")

        _polish_i = st.session_state.pop("_do_polish_one", None)
        if _polish_i is not None:
            with st.spinner(f"✨ {_polish_i + 1}번 자막 다듬는 중..."):
                raw = st.session_state.get(f"_cap_edit_{_polish_i}", "")
                st.session_state[f"_cap_edit_{_polish_i}"] = polish_caption(raw, api_key)

        # ── 사진별 편집 행 ────────────────────────────────
        for i, (path, _) in enumerate(zip(image_paths, captions)):
            c1, c2 = st.columns([1, 3])
            with c1:
                _img = Image.open(path)
                _rot = rotations[i] if i < len(rotations) else 0
                if _rot:
                    _img = _img.rotate(-_rot, expand=True)
                st.image(_img, use_container_width=True)
            with c2:
                st.text_area(
                    f"사진 {i + 1} 자막",
                    key=f"_cap_edit_{i}",
                    height=80,
                    label_visibility="collapsed",
                    placeholder=f"사진 {i + 1} 자막을 입력하세요",
                )
                _b1, _b2 = st.columns(2)
                with _b1:
                    st.button(
                        "🤖 AI 재생성",
                        key=f"_regen_btn_{i}",
                        use_container_width=True,
                        disabled=not api_key,
                        on_click=_trigger_regen_one,
                        args=(i,),
                    )
                with _b2:
                    st.button(
                        "✨ AI 다듬기",
                        key=f"_polish_btn_{i}",
                        use_container_width=True,
                        disabled=not (api_key and st.session_state.get(f"_cap_edit_{i}", "").strip()),
                        on_click=_trigger_polish_one,
                        args=(i,),
                    )

        st.divider()

        # ── 전체 일괄 버튼 ────────────────────────────────
        has_any_caption = any(
            st.session_state.get(f"_cap_edit_{i}", "").strip()
            for i in range(n_caps)
        )
        _ga, _gb = st.columns(2)
        with _ga:
            st.button(
                "🤖 AI 자막 전체 재생성",
                use_container_width=True,
                disabled=not api_key,
                on_click=lambda: st.session_state.update({"_do_regen_all": True}),
                help="모든 사진의 자막을 AI로 새로 생성합니다.",
            )
        with _gb:
            polish_disabled = not (api_key and has_any_caption)
            st.button(
                "✨ AI 자막 전체 다듬기",
                use_container_width=True,
                disabled=polish_disabled,
                on_click=_trigger_polish,
                help="모든 자막을 AI가 다듬고 이모지를 추가합니다.",
            )

        if st.session_state.pop("_do_regen_all", False):
            pb = st.progress(0, text="🤖 전체 자막 재생성 중...")
            for i, path in enumerate(image_paths):
                pb.progress(int(i / n_caps * 100), text=f"🤖 자막 생성 중... ({i + 1}/{n_caps})")
                try:
                    cap, _, _ = generate_caption(path, api_key, _style)
                    st.session_state[f"_cap_edit_{i}"] = cap
                except Exception as e:
                    st.error(f"❌ {i + 1}번 오류: {e}")
            pb.progress(100, text="✅ 완료!")
            st.rerun()

        st.divider()
        col_cancel, col_confirm = st.columns([1, 3])
        with col_cancel:
            if st.button("↩ 취소", use_container_width=True):
                _cleanup_pipeline_temps()
                st.session_state.pop("_pp_stage", None)
                st.rerun()
        with col_confirm:
            _make_btn = "🔄 영상 다시 제작하기" if "_pp_video_bytes" in st.session_state else "🎬 확인하고 영상 제작하기"
            if st.button(_make_btn, type="primary", use_container_width=True):
                _pipeline_stage2()

    # ── 영상 압축 ──────────────────────────────────────────────
    st.divider()
    st.subheader("📦 영상 압축")
    st.caption("완성된 MP4 파일을 업로드하면 용량을 줄여 드립니다.")

    up_comp = st.file_uploader(
        "MP4 파일 업로드",
        type=["mp4"],
        key="compress_upload",
    )

    if up_comp is None:
        st.session_state.pop("_comp_result", None)
    elif st.session_state.get("_comp_source") != up_comp.name:
        st.session_state["_comp_source"] = up_comp.name
        st.session_state.pop("_comp_result", None)

    if up_comp:
        orig_mb = len(up_comp.getbuffer()) / 1024 / 1024
        st.info(f"원본 크기: **{orig_mb:.1f} MB**")

        _cq, _cr = st.columns(2)
        quality = _cq.select_slider(
            "화질",
            options=["최대 압축", "균형", "고화질"],
            value="균형",
            key="comp_quality",
        )
        resolution = _cr.selectbox(
            "해상도",
            ["원본 유지", "720p", "480p"],
            key="comp_res",
        )

        if st.button("📦 압축 시작", type="primary", use_container_width=True, key="comp_btn"):
            crf_map = {"최대 압축": 35, "균형": 28, "고화질": 22}
            res_map  = {"원본 유지": 0, "720p": 720, "480p": 480}
            tmp_in  = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
            tmp_out = None
            try:
                with open(tmp_in, "wb") as f:
                    f.write(up_comp.getbuffer())
                with st.spinner("압축 중... 파일 크기에 따라 수십 초 걸릴 수 있습니다."):
                    tmp_out = compress_video(tmp_in, crf_map[quality], res_map[resolution])
                with open(tmp_out, "rb") as f:
                    comp_bytes = f.read()
                comp_mb = len(comp_bytes) / 1024 / 1024
                st.session_state["_comp_result"]   = comp_bytes
                st.session_state["_comp_mb"]       = comp_mb
                st.session_state["_comp_orig_mb"]  = orig_mb
                st.session_state["_comp_filename"] = f"compressed_{up_comp.name}"
            except Exception as e:
                st.error(f"❌ 압축 실패: {e}")
            finally:
                for _p in [tmp_in, tmp_out]:
                    if _p and os.path.exists(_p):
                        try:
                            os.unlink(_p)
                        except OSError:
                            pass

        if "_comp_result" in st.session_state:
            _orig = st.session_state["_comp_orig_mb"]
            _comp = st.session_state["_comp_mb"]
            _pct  = (1 - _comp / _orig) * 100 if _orig else 0
            st.success(f"✅ {_orig:.1f} MB → {_comp:.1f} MB (용량 {_pct:.0f}% 감소)")
            st.download_button(
                "⬇️ 압축된 영상 다운로드",
                data=st.session_state["_comp_result"],
                file_name=st.session_state["_comp_filename"],
                mime="video/mp4",
                use_container_width=True,
                type="primary",
                key="comp_download",
            )


# ── 파이프라인 ─────────────────────────────────────────────────────────────────

def _cleanup_pipeline_temps():
    """편집 단계에서 저장해 둔 임시 파일 정리."""
    tmp_img_dir = st.session_state.pop("_pp_tmp_img_dir", None)
    tmp_audio   = st.session_state.pop("_pp_tmp_audio", None)
    if tmp_img_dir:
        shutil.rmtree(tmp_img_dir, ignore_errors=True)
    if tmp_audio and os.path.exists(tmp_audio):
        try:
            os.unlink(tmp_audio)
        except OSError:
            pass
    st.session_state.pop("_pp_video_bytes", None)
    st.session_state.pop("_pp_video_filename", None)
    st.session_state.pop("_pp_video_count", None)


def _pipeline_stage1(up_imgs, up_audio, api_key: str, clip_sec: float,
                     caption_style: str, rotations: list, use_ai: bool = True,
                     audio_start: float = 0.0, audio_end: float = 0.0):
    """1단계: 자막 준비(AI 생성 또는 빈 값) 후 session_state에 저장, 편집 화면으로 전환."""
    tmp_img_dir: Optional[str] = None
    tmp_audio:   Optional[str] = None
    try:
        # 이미지 경로 수집
        if up_imgs and hasattr(up_imgs[0], "getbuffer"):
            tmp_img_dir, image_paths = dump_uploads(up_imgs)
        elif up_imgs:
            image_paths = [str(p) for p in up_imgs]
        else:
            st.error("❌ 사진이 없습니다.")
            return

        # 오디오 임시 저장
        if up_audio:
            ext       = Path(up_audio.name).suffix
            tmp_audio = tempfile.NamedTemporaryFile(suffix=ext, delete=False).name
            with open(tmp_audio, "wb") as f:
                f.write(up_audio.getbuffer())

        n = len(image_paths)

        if use_ai:
            pb = st.progress(0, text="준비 중...")
            captions = []
            total_p = total_c = 0
            cap_box = st.expander("📝 AI 자막 생성 중...", expanded=True)

            for i, path in enumerate(image_paths):
                pb.progress(int(i / n * 100), text=f"🤖 자막 생성 중... ({i + 1}/{n})")
                cap, p_tok, c_tok = generate_caption(path, api_key, caption_style)
                captions.append(cap)
                total_p += p_tok
                total_c += c_tok
                with cap_box:
                    c1, c2 = st.columns([1, 4])
                    _prev = Image.open(path)
                    _prev_rot = rotations[i] if rotations and i < len(rotations) else 0
                    if _prev_rot:
                        _prev = _prev.rotate(-_prev_rot, expand=True)
                    c1.image(_prev, use_container_width=True)
                    c2.markdown(f"**{i + 1}번** — _{cap}_")
                    if p_tok:
                        c2.caption(f"입력 {p_tok:,} / 출력 {c_tok:,} 토큰")

            pb.progress(100, text="✅ 자막 생성 완료! 아래에서 수정 후 제작하세요.")
            total_tok = total_p + total_c
            with cap_box:
                st.info(
                    f"**토큰 합계** — 입력 {total_p:,} + 출력 {total_c:,} = **{total_tok:,} 토큰** "
                    f"(사진당 평균 {total_tok // n if n else 0:,})"
                )
        else:
            captions = [""] * n

        # 이전 임시 파일 정리 후 새 컨텍스트 저장
        _cleanup_pipeline_temps()
        st.session_state["_pp_captions"]    = captions
        st.session_state["_pp_image_paths"] = image_paths
        st.session_state["_pp_tmp_img_dir"] = tmp_img_dir
        st.session_state["_pp_tmp_audio"]    = tmp_audio
        st.session_state["_pp_audio_start"] = audio_start
        st.session_state["_pp_audio_end"]   = audio_end
        st.session_state["_pp_clip_sec"]    = clip_sec
        st.session_state["_pp_rotations"]   = rotations
        st.session_state["_pp_stage"]       = "editing"
        # 편집 텍스트 초기화
        for i, cap in enumerate(captions):
            st.session_state[f"_cap_edit_{i}"] = cap

    except Exception as e:
        st.error(f"❌ 오류 발생: {type(e).__name__}: {e}")
        with st.expander("🔍 상세 오류"):
            st.exception(e)
        if tmp_img_dir:
            shutil.rmtree(tmp_img_dir, ignore_errors=True)
        if tmp_audio and os.path.exists(tmp_audio):
            try:
                os.unlink(tmp_audio)
            except OSError:
                pass


def _pipeline_stage2():
    """2단계: 편집된 자막으로 영상 제작."""
    image_paths = st.session_state.get("_pp_image_paths", [])
    captions    = [
        st.session_state.get(f"_cap_edit_{i}", st.session_state["_pp_captions"][i])
        for i in range(len(image_paths))
    ]
    clip_sec    = st.session_state.get("_pp_clip_sec", DEFAULT_CLIP_SEC)
    rotations   = st.session_state.get("_pp_rotations")
    tmp_audio   = st.session_state.get("_pp_tmp_audio")
    audio_start = st.session_state.get("_pp_audio_start", 0.0)
    audio_end   = st.session_state.get("_pp_audio_end",   0.0)

    silent_mp4: Optional[str] = None
    final_mp4:  Optional[str] = None
    try:
        pb = st.progress(0, text="🎬 영상 렌더링 준비...")

        def slide_cb(p: float):
            pb.progress(int(p * 80), text=f"🎬 렌더링 중... {int(p * 100)}%")

        silent_mp4 = build_slideshow(image_paths, captions, clip_sec, rotations, slide_cb)
        pb.progress(82, text="🎵 오디오 처리 중...")

        if tmp_audio and not os.path.exists(tmp_audio):
            st.warning(f"⚠️ 음악 파일을 찾을 수 없습니다: {tmp_audio}")
            tmp_audio = None

        if tmp_audio:
            final_mp4 = add_music(silent_mp4, tmp_audio, audio_start, audio_end)
            os.unlink(silent_mp4)
            silent_mp4 = None
        else:
            final_mp4  = silent_mp4
            silent_mp4 = None

        pb.progress(100, text="✅ 완료!")

        with open(final_mp4, "rb") as f:
            st.session_state["_pp_video_bytes"] = f.read()

        from datetime import date
        base = "video_" + date.today().strftime("%y%m%d")
        count = st.session_state.get("_pp_video_count", 0)
        fname = base if count == 0 else f"{base}({count})"
        st.session_state["_pp_video_filename"] = fname + ".mp4"
        st.session_state["_pp_video_count"] = count + 1

        st.rerun()

    except Exception as e:
        st.error(f"❌ 오류 발생: {type(e).__name__}: {e}")
        with st.expander("🔍 상세 오류"):
            st.exception(e)

    finally:
        for p in [silent_mp4, final_mp4]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


if __name__ == "__main__":
    main()
