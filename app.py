
import os
import re
import io
from pathlib import Path

import streamlit as st
from pypdf import PdfReader
from docx import Document

st.set_page_config(
    page_title="FLM Customer Complaint Assistant",
    page_icon="🛠️",
    layout="centered"
)

st.title("🛠️ FLM Customer Complaint Assistant")
st.write(
    "I will ask a few questions about your complaint and "
    "find the relevant steps from your approved FLM document."
)

# Optional: set FLM_DOC_PATH on the computer/server hosting this app.
FLM_DOC_PATH = os.getenv("FLM_DOC_PATH", "").strip()

SYSTEMS = [
    "Provident",
    "HLR",
    "Siebel",
    "CBS",
    "Other / Not sure"
]

COMPLAINTS = [
    "SIM Modification",
    "Order Deletion",
    "Provisioning",
    "Other complaint"
]


# --------------------------------------------------
# READ FLM DOCUMENT
# --------------------------------------------------

def read_document(filename, file_bytes):
    extension = Path(filename).suffix.lower()

    if extension == ".txt":
        return file_bytes.decode("utf-8", errors="replace")

    if extension == ".pdf":
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []

        for page in reader.pages:
            pages.append(page.extract_text() or "")

        return "\n".join(pages)

    if extension == ".docx":
        doc = Document(io.BytesIO(file_bytes))
        parts = []

        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                parts.append(paragraph.text)

        for table in doc.tables:
            for row in table.rows:
                parts.append(
                    " | ".join(cell.text.strip() for cell in row.cells)
                )

        return "\n".join(parts)

    raise ValueError("Please use a PDF, DOCX, or TXT document.")


def split_document(text, max_chars=900):
    paragraphs = [
        p.strip()
        for p in re.split(r"\n+", text)
        if p.strip()
    ]

    chunks = []
    current = ""

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


# --------------------------------------------------
# SEARCH ONLY THE APPROVED FLM DOCUMENT
# --------------------------------------------------

STOP_WORDS = {
    "the", "and", "for", "with", "from", "what", "when",
    "where", "which", "how", "does", "this", "that",
    "are", "is", "to", "of", "in", "on", "a", "an",
    "i", "we", "you", "my", "please", "steps", "issue",
    "facing", "help", "complaint", "system", "node",
    "tell", "me", "can", "could", "would", "should",
    "about", "explain", "meaning", "brief", "briefly"
}


def get_terms(text):
    words = re.findall(r"[a-zA-Z0-9_-]+", text.lower())

    return {
        word for word in words
        if len(word) > 1 and word not in STOP_WORDS
    }


def find_sections(question, complaint, system, chunks, limit=3):

    terms = get_terms(
        f"{question} {complaint} {system}"
    )

    if not terms:
        return []

    results = []

    for index, chunk in enumerate(chunks):
        lower_chunk = chunk.lower()

        score = sum(
            lower_chunk.count(term)
            for term in terms
        )

        if complaint.lower() in lower_chunk:
            score += 4

        if system and system.lower() in lower_chunk:
            score += 3

        if score > 0:
            results.append((score, index, chunk))

    results.sort(
        key=lambda item: (-item[0], item[1])
    )

    return [
        item[2]
        for item in results[:limit]
    ]


def load_shared_document(path_text):
    path = Path(path_text).expanduser()

    if not path.is_file():
        raise FileNotFoundError(
            f"Document not found: {path}"
        )

    return path.name, path.read_bytes()


# --------------------------------------------------
# SESSION STATE
# Used for temporary question flow, not a database.
# --------------------------------------------------

if "step" not in st.session_state:
    st.session_state.step = 1

if "complaint" not in st.session_state:
    st.session_state.complaint = ""

if "issue" not in st.session_state:
    st.session_state.issue = ""

if "system" not in st.session_state:
    st.session_state.system = ""


def restart_chat():
    for key in [
        "step",
        "complaint",
        "issue",
        "system",
        "other_system",
        "other_complaint",
        "issue_input",
        "complaint_select",
        "system_select"
    ]:
        if key in st.session_state:
            del st.session_state[key]

    st.session_state.step = 1


# --------------------------------------------------
# DOCUMENT SELECTION
# --------------------------------------------------

with st.sidebar:
    st.subheader("Approved FLM Document")

    uploaded_file = st.file_uploader(
        "Upload your FLM procedure",
        type=["pdf", "docx", "txt"]
    )

    st.caption(
        "Alternatively, configure FLM_DOC_PATH on "
        "the computer running Streamlit."
    )

    if st.button("Start New Complaint"):
        restart_chat()
        st.rerun()


document_name = None
document_bytes = None

if uploaded_file is not None:
    document_name = uploaded_file.name
    document_bytes = uploaded_file.getvalue()

elif FLM_DOC_PATH:
    try:
        document_name, document_bytes = load_shared_document(
            FLM_DOC_PATH
        )
    except Exception as error:
        st.error(f"Could not load FLM document: {error}")


chunks = []

if document_bytes is not None:
    try:
        document_text = read_document(
            document_name,
            document_bytes
        )

        chunks = split_document(document_text)

        if not document_text.strip():
            st.warning(
                "No readable text found. Scanned PDFs may require OCR."
            )
        else:
            st.sidebar.success(
                f"Document loaded: {document_name}"
            )

    except Exception as error:
        st.error(f"Document reading error: {error}")


# --------------------------------------------------
# GUIDED QUESTION FLOW
# --------------------------------------------------

if not chunks:

    st.info(
        "Please upload your approved FLM document "
        "using the sidebar before starting."
    )

else:

    # QUESTION 1: COMPLAINT TYPE

    st.subheader("Step 1: Complaint Type")

    selected_complaint = st.selectbox(
        "Which complaint are you facing?",
        COMPLAINTS,
        key="complaint_select"
    )

    if selected_complaint == "Other complaint":
        other_complaint = st.text_input(
            "Enter the complaint name",
            key="other_complaint"
        )
    else:
        other_complaint = ""

    if st.button("Continue to Explanation"):

        if (
            selected_complaint == "Other complaint"
            and not other_complaint.strip()
        ):
            st.warning("Please enter the complaint name.")

        else:
            if selected_complaint == "Other complaint":
                st.session_state.complaint = (
                    other_complaint.strip()
                )
            else:
                st.session_state.complaint = (
                    selected_complaint
                )

            st.session_state.step = 2
            st.rerun()


    # QUESTION 2: BRIEF MEANING

    if st.session_state.step >= 2:

        st.divider()
        st.subheader("Step 2: Brief Explanation")

        st.write(
            f"**Selected complaint:** "
            f"{st.session_state.complaint}"
        )

        definition_sections = find_sections(
            question="definition meaning overview purpose description",
            complaint=st.session_state.complaint,
            system="",
            chunks=chunks,
            limit=1
        )

        if definition_sections:
            st.write(
                "The following is the closest matching text "
                "from your approved FLM document:"
            )

            st.info(definition_sections[0])

        else:
            st.info(
                "A brief definition was not identified in "
                "the FLM document. Please refer to your "
                "approved team definition."
            )

        st.caption(
            "The chatbot will not invent a definition "
            "that is absent from the document."
        )


    # QUESTION 3: EXACT ISSUE

    if st.session_state.step >= 2:

        st.divider()
        st.subheader("Step 3: Describe Your Issue")

        st.write(
            "How can I help you? Where are you facing the issue?"
        )

        issue_text = st.text_area(
            "Describe the problem or error message",
            placeholder=(
                "Example: SIM modification request fails "
                "after submission in Siebel. What error "
                "message appears?"
            ),
            key="issue_input"
        )

        if st.button("Continue to System Selection"):

            if not issue_text.strip():
                st.warning(
                    "Please describe the issue before continuing."
                )

            else:
                st.session_state.issue = issue_text.strip()
                st.session_state.step = 3
                st.rerun()


    # QUESTION 4: SYSTEM / NODE

    if st.session_state.step >= 3:

        st.divider()
        st.subheader("Step 4: Select the Affected Node")

        selected_system = st.selectbox(
            "On which node or system are you facing the issue?",
            SYSTEMS,
            key="system_select"
        )

        if selected_system == "Other / Not sure":
            other_system = st.text_input(
                "Enter the node name if known",
                key="other_system"
            )
        else:
            other_system = ""

        if st.button(
            "Find Relevant FLM Steps",
            type="primary"
        ):

            if (
                selected_system == "Other / Not sure"
                and other_system.strip()
            ):
                st.session_state.system = other_system.strip()
            else:
                st.session_state.system = selected_system

            st.session_state.step = 4
            st.rerun()


    # QUESTION 5: DISPLAY RELEVANT DOCUMENT TEXT

    if st.session_state.step >= 4:

        st.divider()
        st.subheader("Step 5: Troubleshooting Result")

        st.write(
            f"**Complaint:** {st.session_state.complaint}"
        )

        st.write(
            f"**Reported issue:** {st.session_state.issue}"
        )

        st.write(
            f"**Node/system:** {st.session_state.system}"
        )

        relevant = find_sections(
            question=st.session_state.issue,
            complaint=st.session_state.complaint,
            system=st.session_state.system,
            chunks=chunks,
            limit=3
        )

        if relevant:

            st.write(
                "Relevant sections found in your FLM document:"
            )

            for number, section in enumerate(
                relevant, start=1
            ):
                with st.expander(
                    f"Relevant section {number}",
                    expanded=(number == 1)
                ):
                    st.text(section)

            st.warning(
                "These are matching document excerpts, not "
                "independently verified instructions. Follow "
                "your approved operational procedure."
            )

        else:

            st.warning(
                "No relevant section was found for this issue "
                "and node in the provided FLM document. "
                "Try different keywords or contact your FLM "
                "document owner. No external steps have been added."
            )

        if st.button("Start Another Complaint"):
            restart_chat()
            st.rerun()


# --------------------------------------------------
# PRIVACY NOTICE
# --------------------------------------------------

st.divider()

st.caption(
    "Privacy: this code does not deliberately save chat "
    "transcripts to files or a database and does not call "
    "an external AI API. Data is processed temporarily by "
    "the running application. Hosting logs, access controls, "
    "shared-folder permissions, and platform-level handling "
    "must be managed separately."
)
