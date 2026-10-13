import os
import re
from pathlib import Path

import streamlit as st
from pypdf import PdfReader
from docx import Document

st.set_page_config(page_title="FLM Complaint Assistant", page_icon="🛠️", layout="centered")

st.title("🛠️ FLM Customer Complaint Assistant")
st.caption("Answers are based only on your approved FLM document. No chat history is saved by this app.")

# Configure a path on the machine where Streamlit runs.
# Example: FLM_DOC_PATH=/path/to/shared/FLM_SOP.pdf
DEFAULT_DOC_PATH = os.getenv("FLM_DOC_PATH", "").strip()


def read_document_bytes(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".txt":
        return data.decode("utf-8", errors="replace")
    if suffix == ".pdf":
        import io
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        import io
        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        return "\n".join(parts)
    raise ValueError("Unsupported file type. Please use PDF, DOCX, or TXT.")


def split_into_chunks(text: str, max_chars: int = 900):
    # Preserve paragraph/step boundaries where possible.
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    chunks, current = [], ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[start:start + max_chars])
        elif not current:
            current = paragraph
        elif len(current) + len(paragraph) + 1 <= max_chars:
            current += "\n" + paragraph
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def find_relevant_chunks(question: str, chunks, limit: int = 4):
    # Basic local keyword search; does not call an external AI/API.
    stop_words = {
        "the", "and", "for", "with", "from", "what", "when", "where", "which",
        "how", "does", "this", "that", "are", "is", "to", "of", "in", "on",
        "a", "an", "i", "we", "you", "my", "please", "steps", "complaint"
    }
    terms = {
        token for token in re.findall(r"[a-zA-Z0-9_-]+", question.lower())
        if len(token) > 1 and token not in stop_words
    }
    if not terms:
        return []
    scored = []
    for index, chunk in enumerate(chunks):
        lower = chunk.lower()
        score = sum(lower.count(term) for term in terms)
        if score:
            scored.append((score, index, chunk))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:limit]]


def load_configured_document(path_text: str):
    path = Path(path_text).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Configured FLM document was not found: {path}")
    if path.suffix.lower() not in {".pdf", ".docx", ".txt"}:
        raise ValueError("FLM_DOC_PATH must point to a PDF, DOCX, or TXT file.")
    return path.name, path.read_bytes()


with st.sidebar:
    st.subheader("FLM document")
    st.write("Choose a document upload, or configure `FLM_DOC_PATH` on the server.")
    uploaded = st.file_uploader("Upload approved FLM document", type=["pdf", "docx", "txt"])
    st.caption("Uploaded file contents are processed in app memory and are not written to a file by this code.")

doc_name, doc_bytes = None, None
if uploaded is not None:
    doc_name, doc_bytes = uploaded.name, uploaded.getvalue()
elif DEFAULT_DOC_PATH:
    try:
        doc_name, doc_bytes = load_configured_document(DEFAULT_DOC_PATH)
    except Exception as exc:
        st.error(f"Could not load the configured document: {exc}")
else:
    st.info(
        "Upload your approved FLM procedure in the sidebar, or set the `FLM_DOC_PATH` "
        "environment variable to a document path available to the Streamlit server."
    )

document_text = ""
chunks = []
if doc_bytes is not None:
    try:
        document_text = read_document_bytes(doc_name, doc_bytes)
        chunks = split_into_chunks(document_text)
        if not document_text.strip():
            st.warning("No readable text was found. If this is a scanned PDF, run OCR first.")
        else:
            st.success(f"Loaded: {doc_name} · {len(chunks)} text sections")
    except Exception as exc:
        st.error(f"Unable to read the document: {exc}")

st.markdown("### Ask about a complaint")
question = st.text_input(
    "Complaint type or question",
    placeholder="Example: What are the FLM steps for SIM modification?",
)
ask = st.button("Find steps", type="primary", disabled=not bool(chunks and question.strip()))

if ask:
    matches = find_relevant_chunks(question, chunks)
    if matches:
        st.markdown("#### Relevant text from your FLM document")
        st.caption("The text below is extracted from your document. Follow the exact approved procedure.")
        for i, match in enumerate(matches, start=1):
            st.markdown(f"**Section {i}**")
            st.text(match)
        st.warning(
            "This basic version retrieves matching text; it does not independently verify "
            "operational steps or perform any system/database changes."
        )
    else:
        st.warning(
            "I could not find a matching section in the provided FLM document. "
            "Please try the complaint name or a keyword used in the document. "
            "I will not invent steps from external sources."
        )

st.divider()
st.caption(
    "Privacy note: this app code does not save chat transcripts, create a conversation-history "
    "database, or call an external AI API. The question and extracted text are still processed "
    "temporarily in the running Streamlit session. Hosting provider logs, access controls, and "
    "the privacy of the shared folder must be managed separately."
)
