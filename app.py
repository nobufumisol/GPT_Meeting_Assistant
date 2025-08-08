import streamlit as st
import openai
import os
import io
import base64
from PIL import Image
from PyPDF2 import PdfReader
from docx2txt import process as docx_process
import pandas as pd
import mammoth
import pytesseract
import tempfile

# =========================
# 初期設定
# =========================
st.set_page_config(page_title="GPT Meeting Assistant")
openai.api_key = st.secrets["openai_key"]

# =========================
# アジェンダ読み込み処理
# =========================
def read_file(file):
    file_type = file.type
    if file_type in ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
            tmp.write(file.read())
            tmp_path = tmp.name
        with open(tmp_path, "rb") as docx_file:
            result = mammoth.convert_to_text(docx_file)
            return result.value
    elif file_type in ["application/pdf"]:
        reader = PdfReader(file)
        return "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
    elif file_type in ["text/plain"]:
        return file.read().decode("utf-8")
    elif file_type in ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]:
        df = pd.read_excel(file)
        return df.to_string(index=False)
    elif file_type in ["image/png", "image/jpeg", "image/jpg", "image/gif"]:
        image = Image.open(file)
        return pytesseract.image_to_string(image, lang="jpn")
    else:
        return "(このファイル形式は現在サポートされていません)"

# =========================
# ファイルダウンロード用ユーティリティ
# =========================
def get_download_button(content, filename, label, key):
    b64 = base64.b64encode(content.encode()).decode()
    href = f'<a href="data:file/txt;base64,{b64}" download="{filename}">{label}</a>'
    st.markdown(href, unsafe_allow_html=True)

# =========================
# UI 構成
# =========================
st.title("GPT Meeting Assistant")

uploaded_audio = st.file_uploader("🎧 音声ファイルをアップロード", type=["wav", "mp3", "m4a", "mp4"])
prompt_input = st.text_area("🤖 プロンプト（未入力なら「パートナー」視点）", "")
agenda_files = st.file_uploader("📎 アジェンダ資料（複数可・最大10件）", accept_multiple_files=True)

if st.button("💬 分析を開始", type="primary"):
    if uploaded_audio is None:
        st.error("音声ファイルをアップロードしてください。")
    else:
        # --------------------------
        # 音声ファイルを一時保存
        # --------------------------
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_audio:
            tmp_audio.write(uploaded_audio.read())
            temp_audio_path = tmp_audio.name

        # --------------------------
        # Whisper APIで文字起こし
        # --------------------------
        with open(temp_audio_path, "rb") as audio_file:
            st.info("Whisper API で文字起こし中...")
            transcription = openai.Audio.transcribe(
                model="whisper-1",
                file=audio_file,
                language="ja"
            )
        text = transcription["text"]

        # --------------------------
        # アジェンダまとめて読み込み
        # --------------------------
        agenda_texts = []
        if agenda_files:
            for i, f in enumerate(agenda_files[:10]):
                st.success(f"{i+1}. {f.name} を読み込みました")
                agenda_texts.append(read_file(f))
        combined_agenda = "\n\n".join(agenda_texts)

        # --------------------------
        # プロンプト設定
        # --------------------------
        default_partner_prompt = (
            "あなたは信頼できるパートナーとして、会話の流れを大切にしながら、"
            "素晴らしい視点には共感を示し、議論に足りない視点には誰もがハッとするような問いをユーモアを交えて提示できます。\n"
            "問いを出すときは、なぜその問いが必要なのか、答えなければ起こり得るリスクや未来のズレを具体例で示してください。\n"
            "たとえば「これが話されていないと、後から〇〇で揉める可能性がある」といった視点を添えてください。\n"
            "問いのトーンは柔らかく、それでいて鋭く。「確かに…それ、大事ですね」と思わせる問いを目指してください。"
        )
        role_prompt = prompt_input.strip() if prompt_input.strip() else default_partner_prompt

        # --------------------------
        # ChatGPT要約
        # --------------------------
        st.info("ChatGPT に要約依頼中...")
        summary_prompt = f"""
以下は会議の文字起こしです。以下の4点を遵守し、事実のみをビジネス向けの丁寧な文章でまとめてください。
1. 議論のポイントを漏れなく
2. 読みやすく
3. 簡潔に
4. 構造的に

《アジェンダ》
{combined_agenda}

《文字起こし》
{text}
        """
        summary_response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": summary_prompt}]
        )
        summary_result = summary_response["choices"][0]["message"]["content"]

        # --------------------------
        # ChatGPT提案
        # --------------------------
        st.info("ChatGPT に提案依頼中...")
        suggestion_prompt = f"""
以下は会議の文字起こしです。
《アジェンダ》
{combined_agenda}

《文字起こし》
{text}

この内容をもとに、参加者の気づきを促すような
- 改善点
- 問い
- リスクとその回避策

を具体例や理由を添えて、深い共感が得られる形で提案してください。
        """
        suggestion_response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": role_prompt},
                {"role": "user", "content": suggestion_prompt}
            ]
        )
        suggestion_result = suggestion_response["choices"][0]["message"]["content"]

        # --------------------------
        # 表示・ダウンロード
        # --------------------------
        st.success("✅ 分析完了！")

        st.subheader("📄 要約")
        st.write(summary_result)
        get_download_button(summary_result, "summary.txt", "⬇ 要約をダウンロード", key="summary")

        st.subheader("💡 提案")
        st.write(suggestion_result)
        get_download_button(suggestion_result, "suggestion.txt", "⬇ 提案をダウンロード", key="suggestion")
