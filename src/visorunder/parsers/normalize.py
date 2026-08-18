"""Normalizacion de texto OCR.

Solo se normaliza el ALFABETO, nunca la magnitud del numero:
en un ROI declarado numerico, una 'O' solo puede ser un 0 y una 'l' solo puede
ser un 1. Eso es correccion de caracteres, no invencion de valores.

Cualquier ambiguedad que afecte al VALOR (por ejemplo "187" cuando lo esperado
es "1.87") se deja intacta y se marca como sospechosa aguas arriba.
"""

from __future__ import annotations

import re
import unicodedata

#: Confusiones tipicas del OCR cuando el contenido es numerico.
DIGIT_CONFUSIONS = {
    "O": "0", "o": "0", "Q": "0", "D": "0",
    "l": "1", "I": "1", "i": "1", "|": "1", "!": "1", "]": "1", "[": "1",
    "Z": "2", "z": "2",
    "E": "3",
    "A": "4",
    "S": "5", "s": "5",
    "G": "6", "b": "6",
    "T": "7", "?": "7",
    "B": "8",
    "g": "9", "q": "9",
}

_WHITESPACE = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    if not text:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def clean(text: str) -> str:
    """Limpieza generica: recorta y colapsa espacios."""
    if text is None:
        return ""
    return _WHITESPACE.sub(" ", str(text)).strip()


def normalize_label(text: str) -> str:
    """Normaliza una etiqueta para compararla: sin acentos, minusculas."""
    return _WHITESPACE.sub(" ", strip_accents(clean(text)).lower()).strip()


def normalize_digits(text: str, *, keep: str = ":.,") -> str:
    """Convierte confusiones alfabeticas a digitos en un contexto numerico.

    >>> normalize_digits("O5:2B")
    '05:28'
    >>> normalize_digits("l.87")
    '1.87'
    """
    if not text:
        return ""
    out = []
    for ch in clean(text):
        if ch.isdigit() or ch in keep:
            out.append(ch)
        elif ch in DIGIT_CONFUSIONS:
            out.append(DIGIT_CONFUSIONS[ch])
        elif ch.isspace():
            out.append(" ")
        # cualquier otro caracter se descarta
    return "".join(out).strip()


def decimal_separator_to_dot(text: str) -> str:
    """Unifica la coma decimal a punto. No anade separadores que no existan."""
    return (text or "").replace(",", ".")


def extract_numbers(text: str) -> list:
    """Extrae todos los numeros (con decimales) presentes en el texto."""
    if not text:
        return []
    return [float(m) for m in re.findall(r"\d+(?:\.\d+)?", decimal_separator_to_dot(text))]


def extract_integers(text: str) -> list:
    if not text:
        return []
    return [int(m) for m in re.findall(r"\d+", text)]
