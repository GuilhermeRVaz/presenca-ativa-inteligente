from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import streamlit as st

from app.core.config import settings


SCHEMA = "busca_ativa_v2"
CLASS_OPTIONS = [
    "6 ANO 6A INTEGRAL 9H ANUAL",
    "6 ANO 6B INTEGRAL 9H ANUAL",
    "7 ANO 7A INTEGRAL 9H ANUAL",
    "7 ANO 7B INTEGRAL 9H ANUAL",
    "8 ANO 8A INTEGRAL 9H ANUAL",
    "8 ANO 8B INTEGRAL 9H ANUAL",
    "9 ANO 9A INTEGRAL 9H ANUAL",
]


@dataclass(frozen=True)
class NormalizedStudentInput:
    name: str
    ra: str
    class_name: str
    grade: str | None
    active: bool


def normalize_ra(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    digits = digits.lstrip("0")
    if len(digits) > 9:
        digits = digits[:-1]
    return digits


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits and not digits.startswith("55"):
        digits = "55" + digits
    return digits


def short_class_name(class_name: str) -> str:
    match = re.search(r"(\d)\s*ANO\s*(\d[A-Z])", class_name or "", flags=re.I)
    return match.group(2).upper() if match else class_name


def relationship_label(value: str) -> str:
    text = (value or "").strip().lower()
    mapping = {
        "mae": "Mae/Responsavel",
        "mãe": "Mae/Responsavel",
        "pai": "Pai/Responsavel",
        "avo": "Avo/Responsavel",
        "avó": "Avo/Responsavel",
        "avô": "Avo/Responsavel",
        "responsavel": "Responsavel",
        "responsável": "Responsavel",
    }
    return mapping.get(text, value.strip() or "Responsavel")


@st.cache_resource
def supabase_client():
    from supabase import create_client
    from supabase.lib.client_options import SyncClientOptions

    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError("SUPABASE_URL e SUPABASE_KEY precisam estar no .env")
    return create_client(
        settings.supabase_url,
        settings.supabase_key,
        options=SyncClientOptions(postgrest_client_timeout=90.0),
    )


def db():
    return supabase_client().schema(SCHEMA)


def school_id() -> str:
    if not settings.default_school_id:
        raise RuntimeError("DEFAULT_SCHOOL_ID precisa estar configurado no .env")
    return settings.default_school_id


def find_students(query: str) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    sid = school_id()
    client = db().table("students").select("*").eq("school_id", sid)
    ra = normalize_ra(q)
    if ra and len(ra) >= 6:
        res = client.eq("ra", ra).limit(25).execute()
    else:
        res = client.ilike("name", f"%{q}%").limit(25).execute()
    return res.data or []


def get_guardians(student_id: str) -> list[dict[str, Any]]:
    return (
        db()
        .table("student_guardians")
        .select("student_id,guardian_id,relationship,is_primary,guardians(id,name,phone_e164,wa_jid,active)")
        .eq("student_id", student_id)
        .order("is_primary", desc=True)
        .execute()
        .data
        or []
    )


def get_legacy_contact(ra: str) -> dict[str, Any] | None:
    rows = (
        supabase_client()
        .schema("public")
        .table("contacts")
        .select("*")
        .eq("ra", ra)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def upsert_student(data: NormalizedStudentInput) -> dict[str, Any]:
    sid = school_id()
    payload = {
        "school_id": sid,
        "ra": data.ra,
        "name": data.name,
        "class_name": data.class_name,
        "grade": data.grade,
        "active": data.active,
    }
    rows = (
        db()
        .table("students")
        .select("id")
        .eq("school_id", sid)
        .eq("ra", data.ra)
        .limit(1)
        .execute()
        .data
        or []
    )
    if rows:
        return db().table("students").update(payload).eq("id", rows[0]["id"]).execute().data[0]
    return db().table("students").insert(payload).execute().data[0]


def update_legacy_contact(
    *,
    ra: str,
    name: str,
    class_name: str,
    birth_date: str,
    guardians: list[tuple[str, str]],
) -> None:
    payload: dict[str, Any] = {
        "ra": ra,
        "nome_aluno": name,
        "turma": short_class_name(class_name),
        "situacao": "",
        "data_nascimento": birth_date.strip(),
    }
    for index in range(3):
        rel, phone = guardians[index] if index < len(guardians) else ("", "")
        payload[f"responsavel_{index + 1}"] = rel
        payload[f"telefone_{index + 1}"] = phone

    existing = get_legacy_contact(ra)
    table = supabase_client().schema("public").table("contacts")
    if existing:
        table.update(payload).eq("id", existing["id"]).execute()
    else:
        table.insert(payload).execute()


def upsert_guardian_and_link(
    *,
    student_id: str,
    relationship: str,
    phone_raw: str,
    primary: bool,
) -> str:
    phone = normalize_phone(phone_raw)
    if not re.fullmatch(r"\d{10,15}", phone):
        raise ValueError("Telefone invalido. Use DDD + numero, por exemplo 14999999999.")

    sid = school_id()
    guardian_payload = {
        "school_id": sid,
        "name": relationship_label(relationship),
        "phone_e164": phone,
        "wa_jid": f"{phone}@s.whatsapp.net",
        "active": True,
    }
    existing = (
        db()
        .table("guardians")
        .select("id")
        .eq("school_id", sid)
        .eq("phone_e164", phone)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        guardian_id = existing[0]["id"]
        db().table("guardians").update(guardian_payload).eq("id", guardian_id).execute()
    else:
        guardian_id = db().table("guardians").insert(guardian_payload).execute().data[0]["id"]

    if primary:
        db().table("student_guardians").update({"is_primary": False}).eq("student_id", student_id).execute()

    db().table("student_guardians").upsert(
        {
            "student_id": student_id,
            "guardian_id": guardian_id,
            "relationship": normalize_relationship(relationship),
            "is_primary": primary,
        },
        on_conflict="student_id,guardian_id",
    ).execute()

    upsert_identity(phone=phone, guardian_id=guardian_id)
    return guardian_id


def normalize_relationship(value: str) -> str:
    text = (value or "").strip().lower()
    mapping = {"mãe": "mae", "mae": "mae", "pai": "pai", "vô": "avo", "vó": "avo", "avo": "avo"}
    return mapping.get(text, text or "responsavel")


def upsert_identity(*, phone: str, guardian_id: str) -> None:
    sid = school_id()
    payload = {
        "school_id": sid,
        "phone_e164": phone,
        "wa_jid": f"{phone}@s.whatsapp.net",
        "guardian_id": guardian_id,
        "confidence": "HIGH",
        "source": "manual",
    }
    rows = (
        db()
        .table("phone_identity_map")
        .select("id")
        .eq("school_id", sid)
        .eq("phone_e164", phone)
        .limit(1)
        .execute()
        .data
        or []
    )
    if rows:
        db().table("phone_identity_map").update(payload).eq("id", rows[0]["id"]).execute()
    else:
        db().table("phone_identity_map").insert(payload).execute()


def delete_link(student_id: str, guardian_id: str) -> None:
    db().table("student_guardians").delete().eq("student_id", student_id).eq("guardian_id", guardian_id).execute()


def render_student_picker() -> dict[str, Any] | None:
    st.subheader("Localizar aluno")
    query = st.text_input("Nome ou RA", placeholder="Ex: EMANUELA ou 120116275")
    if not query:
        return None

    results = find_students(query)
    if not results:
        st.info("Nenhum aluno encontrado no schema operacional.")
        return None

    labels = {
        f"{row['name']} | RA {row['ra']} | {row['class_name']}": row for row in results
    }
    selected = st.selectbox("Resultados", list(labels.keys()))
    return labels[selected]


def render_student_form(student: dict[str, Any] | None) -> dict[str, Any] | None:
    st.subheader("Aluno")
    with st.form("student_form"):
        name = st.text_input("Nome", value=(student or {}).get("name", ""))
        ra = st.text_input("RA", value=(student or {}).get("ra", ""))
        current_class = (student or {}).get("class_name") or CLASS_OPTIONS[0]
        class_name = st.selectbox(
            "Turma",
            CLASS_OPTIONS,
            index=CLASS_OPTIONS.index(current_class) if current_class in CLASS_OPTIONS else 0,
        )
        grade = st.text_input("Grade/Série extra", value=(student or {}).get("grade") or "")
        active = st.checkbox("Ativo", value=(student or {}).get("active", True))
        birth_date = st.text_input("Nascimento no contato legado", placeholder="dd/mm/aaaa")
        sync_legacy = st.checkbox("Atualizar/criar public.contacts", value=True)
        submitted = st.form_submit_button("Salvar aluno", type="primary")

    if not submitted:
        return student

    normalized = NormalizedStudentInput(
        name=name.strip().upper(),
        ra=normalize_ra(ra),
        class_name=class_name,
        grade=grade.strip() or None,
        active=active,
    )
    if not normalized.name or not normalized.ra:
        st.error("Nome e RA sao obrigatorios.")
        return student
    saved = upsert_student(normalized)
    if sync_legacy:
        legacy = get_legacy_contact(normalized.ra) or {}
        update_legacy_contact(
            ra=normalized.ra,
            name=normalized.name,
            class_name=normalized.class_name,
            birth_date=birth_date or legacy.get("data_nascimento", ""),
            guardians=[
                (legacy.get("responsavel_1") or "", legacy.get("telefone_1") or ""),
                (legacy.get("responsavel_2") or "", legacy.get("telefone_2") or ""),
                (legacy.get("responsavel_3") or "", legacy.get("telefone_3") or ""),
            ],
        )
    st.success("Aluno salvo.")
    return saved


def render_guardians(student: dict[str, Any]) -> None:
    st.subheader("Responsaveis vinculados")
    links = get_guardians(student["id"])
    if links:
        for link in links:
            guardian = link.get("guardians") or {}
            cols = st.columns([2, 2, 2, 1, 1])
            cols[0].write(guardian.get("name", ""))
            cols[1].write(guardian.get("phone_e164", ""))
            cols[2].write(link.get("relationship", ""))
            cols[3].write("Principal" if link.get("is_primary") else "")
            if cols[4].button("Remover", key=f"remove-{student['id']}-{link['guardian_id']}"):
                delete_link(student["id"], link["guardian_id"])
                st.rerun()
    else:
        st.warning("Aluno sem responsavel vinculado.")

    st.markdown("### Adicionar ou atualizar responsavel")
    with st.form("guardian_form"):
        col1, col2, col3 = st.columns([1, 2, 1])
        relationship = col1.selectbox("Vinculo", ["mae", "pai", "avo", "responsavel"])
        phone = col2.text_input("Telefone", placeholder="14999999999")
        primary = col3.checkbox("Principal", value=not bool(links))
        submitted = st.form_submit_button("Salvar responsavel")

    if submitted:
        try:
            upsert_guardian_and_link(
                student_id=student["id"],
                relationship=relationship,
                phone_raw=phone,
                primary=primary,
            )
            legacy = get_legacy_contact(student["ra"]) or {}
            legacy_guardians = [
                (legacy.get("responsavel_1") or "", legacy.get("telefone_1") or ""),
                (legacy.get("responsavel_2") or "", legacy.get("telefone_2") or ""),
                (legacy.get("responsavel_3") or "", legacy.get("telefone_3") or ""),
            ]
            normalized_phone = normalize_phone(phone)
            if all(existing_phone != normalized_phone for _, existing_phone in legacy_guardians):
                for index, (_, existing_phone) in enumerate(legacy_guardians):
                    if not existing_phone:
                        legacy_guardians[index] = (relationship, normalized_phone)
                        break
            update_legacy_contact(
                ra=student["ra"],
                name=student["name"],
                class_name=student["class_name"],
                birth_date=legacy.get("data_nascimento", ""),
                guardians=legacy_guardians,
            )
            st.success("Responsavel salvo e vinculado.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def render_quick_create() -> None:
    st.subheader("Cadastro rapido")
    with st.form("quick_create_form"):
        name = st.text_input("Nome completo").upper()
        ra = st.text_input("RA")
        class_name = st.selectbox("Turma", CLASS_OPTIONS, key="quick_class")
        birth_date = st.text_input("Nascimento", placeholder="dd/mm/aaaa")
        rel1 = st.selectbox("Responsavel 1", ["mae", "pai", "avo", "responsavel"], key="rel1")
        phone1 = st.text_input("Telefone 1")
        rel2 = st.selectbox("Responsavel 2", ["", "mae", "pai", "avo", "responsavel"], key="rel2")
        phone2 = st.text_input("Telefone 2")
        rel3 = st.selectbox("Responsavel 3", ["", "mae", "pai", "avo", "responsavel"], key="rel3")
        phone3 = st.text_input("Telefone 3")
        submitted = st.form_submit_button("Cadastrar aluno e responsaveis", type="primary")

    if not submitted:
        return

    saved = upsert_student(
        NormalizedStudentInput(
            name=name.strip().upper(),
            ra=normalize_ra(ra),
            class_name=class_name,
            grade=None,
            active=True,
        )
    )
    guardians = [(rel1, normalize_phone(phone1))]
    for rel, phone in [(rel2, phone2), (rel3, phone3)]:
        if rel and phone:
            guardians.append((rel, normalize_phone(phone)))
    update_legacy_contact(
        ra=saved["ra"],
        name=saved["name"],
        class_name=saved["class_name"],
        birth_date=birth_date,
        guardians=guardians,
    )
    for index, (rel, phone) in enumerate(guardians):
        if phone:
            upsert_guardian_and_link(
                student_id=saved["id"],
                relationship=rel,
                phone_raw=phone,
                primary=index == 0,
            )
    st.success(f"Cadastro salvo: {saved['name']} | RA {saved['ra']}")


def main() -> None:
    st.set_page_config(page_title="CRUD Supabase - PAI", layout="wide")
    st.title("CRUD Supabase - Presenca Ativa")
    st.caption("Edicao manual de alunos, responsaveis, vinculos e contatos legados.")

    try:
        st.sidebar.success(f"Escola: {school_id()}")
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    tab_search, tab_create = st.tabs(["Buscar e editar", "Cadastro rapido"])
    with tab_search:
        selected = render_student_picker()
        edited = render_student_form(selected) if selected else None
        if edited:
            render_guardians(edited)
            with st.expander("Contato legado"):
                st.json(get_legacy_contact(edited["ra"]) or {})
    with tab_create:
        render_quick_create()


if __name__ == "__main__":
    main()
