"""Carga y busqueda deterministica sobre la base de conocimiento de FAQs existente."""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_QA_PATTERN = re.compile(r"Q:\s*(?P<question>.+?)\s*\nA:\s*(?P<answer>.+?)(?=\n\s*\n|\Z)", re.DOTALL)
_CONTACT_PATTERN = re.compile(r"(?m)^5\. CONTACTO\s*\n(?P<body>[\s\S]*)\Z")
# Function words plus generic words that must never retrieve an entry on their own
# (e.g. "quien", "numero", "evento" appear in unrelated entries).
_STOP_WORDS = {
    "a", "al", "como", "con", "cual", "cuales", "cuanto", "cuantos", "de", "del", "el", "en",
    "es", "esta", "este", "estoy", "hay", "la", "las", "lo", "los", "me", "mi", "mis", "para",
    "parachute", "persona", "por", "puedo", "puede", "pueden", "que", "quiero", "sa", "salto",
    "saltar", "se", "su", "sus", "un", "una", "y", "evento", "quien", "numero", "informacion",
    "pregunta", "saber", "dime", "decir", "debo", "debe", "deberia", "tengo", "tiene", "necesito",
    "hacer", "hice", "incluye", "existe", "favor", "gracias", "hola", "sobre", "otra", "otro",
    "tus", "tu", "usted", "ustedes", "seria", "hay", "algun", "alguna", "mucho", "muy",
    "paracaidismo", "paracaida", "paracaidas",
}
# Controlled query-side synonyms (keys are stemmed). Values are words used by the corpus.
_QUERY_ALIASES = {
    "pongo": "ropa", "ponerme": "ropa", "vestir": "ropa", "vestirme": "ropa", "vestirse": "ropa",
    "vestimenta": "ropa", "visto": "ropa", "atuendo": "ropa", "outfit": "ropa", "calzado": "ropa",
    "zapato": "ropa", "uniforme": "ropa",
    "gopro": "camara", "grabar": "camara", "filmar": "camara", "grabacion": "camara",
    "kilo": "peso", "kg": "peso", "kilogramo": "peso", "libra": "peso", "lb": "peso", "pesar": "peso",
    "nino": "menor", "nina": "menor", "adolescente": "menor", "hijo": "menor", "hija": "menor",
    "embarazada": "embarazo", "embarazo": "embarazo",
    "whatsapp": "telefono", "llamar": "telefono", "tel": "telefono", "celular": "telefono",
    "email": "correo", "mail": "correo", "electronico": "correo",
    "ubicacion": "donde", "lugar": "donde", "direccion": "donde", "sede": "donde", "localizacion": "donde",
    "empieza": "cuando", "inicia": "cuando", "comienza": "cuando",
    "inicio": "cuando", "arranca": "cuando",
}
# "celular" is only a contact synonym when the user asks for a number, not about devices.
_DEVICE_CONTEXT = re.compile(r"\b(?:llevar|usar|grabar|subir|traer|permit\w*)\b")
_CONTACT_TERMS = {"telefono", "correo", "contacto", "instagram", "facebook", "redes", "web", "sitio"}
_SHORT_TERMS = {"kg", "lb"}
# Applied before plural folding: "hora" asks when it starts, "horas" asks how long it lasts.
_RAW_ALIASES = {"hora": "cuando", "horario": "cuando", "anos": "edad", "ano": "edad", "duracion": "dura"}
_ALIAS_TARGETS = set(_QUERY_ALIASES.values()) | set(_RAW_ALIASES.values())
CONTACT_QUESTION = "Telefono, correo, redes sociales y sitio web de contacto"


class FaqServiceError(RuntimeError):
    """La fuente de FAQs no existe, esta vacia o no se pudo interpretar."""


@dataclass(frozen=True)
class FaqEntry:
    question: str
    answer: str


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    plain = re.sub(r"[‐-―−]", "-", plain)
    return re.sub(r"\bgo[\s\-]?pro(s)?\b", "gopro", plain)


def _stem(word: str) -> str:
    """Light Spanish plural folding, applied identically to queries and corpus."""
    if len(word) > 4 and word.endswith("es") and word[-3] not in "aeiou":
        return word[:-2]
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def _terms(text: str, *, query: bool = False) -> set[str]:
    normalized = _normalize(text)
    terms = set()
    for word in re.findall(r"[a-z0-9]+", normalized):
        if word in _STOP_WORDS or (len(word) <= 2 and word not in _SHORT_TERMS):
            continue
        if query and word in _RAW_ALIASES:
            terms.add(_RAW_ALIASES[word])
            continue
        stem = _stem(word)
        if query:
            if stem == "celular" and _DEVICE_CONTEXT.search(normalized):
                stem = "camara"
            stem = _QUERY_ALIASES.get(stem, stem)
        if stem not in _STOP_WORDS:
            terms.add(stem)
    return terms


def load_knowledge_base_text(path: str | Path) -> str:
    faq_path = Path(path)
    try:
        content = faq_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as error:
        raise FaqServiceError(f"No se encontro el archivo FAQ: {faq_path}") from error

    if not content:
        raise FaqServiceError(f"El archivo FAQ esta vacio: {faq_path}")

    return content


def parse_faq_entries(knowledge_base_text: str) -> list[FaqEntry]:
    entries = [
        FaqEntry(question=match.group("question").strip(), answer=match.group("answer").strip())
        for match in _QA_PATTERN.finditer(knowledge_base_text)
    ]
    if not entries:
        raise FaqServiceError("No se encontraron pares Q/A en la fuente de FAQs.")
    contact = _CONTACT_PATTERN.search(knowledge_base_text)
    if contact:
        body = contact.group("body").strip()
        if body:
            entries.append(FaqEntry(question=CONTACT_QUESTION, answer=body))
    return entries


@dataclass(frozen=True)
class FaqService:
    knowledge_base_text: str
    entries: list[FaqEntry]

    @classmethod
    def from_path(cls, path: str | Path) -> "FaqService":
        text = load_knowledge_base_text(path)
        return cls(knowledge_base_text=text, entries=parse_faq_entries(text))

    def search_faq(self, query: str, max_results: int = 3) -> list[FaqEntry]:
        """Busqueda por palabras clave (determinista) sobre las preguntas/respuestas conocidas."""
        clean_query = query.strip()
        if not clean_query:
            return []

        query_tokens = _terms(clean_query, query=True)
        if not query_tokens:
            return []

        entry_terms = [_terms(f"{entry.question} {entry.answer}") for entry in self.entries]
        question_terms = [_terms(entry.question) for entry in self.entries]
        document_frequency = {
            token: sum(token in terms for terms in entry_terms) for token in query_tokens
        }
        wants_contact = bool(query_tokens & _CONTACT_TERMS)
        scored: list[tuple[int, int, int, FaqEntry]] = []
        for index, (entry, terms, in_question) in enumerate(zip(self.entries, entry_terms, question_terms)):
            matches = query_tokens & terms
            if not matches:
                continue
            if len(matches) == 1:
                # One shared word is enough only when it is specific to this entry and is
                # either the topic of its question or most of what the user asked about.
                (term,) = matches
                if document_frequency[term] != 1:
                    continue
                # Curated alias concepts (e.g. "embarazo") identify the topic by themselves.
                if term not in in_question and term not in _ALIAS_TARGETS and len(query_tokens) > 2:
                    continue
            is_contact = entry.question == CONTACT_QUESTION
            scored.append((int(wants_contact and is_contact), len(matches), -index, entry))

        scored.sort(key=lambda item: item[:3], reverse=True)
        return [entry for *_, entry in scored[:max_results]]
