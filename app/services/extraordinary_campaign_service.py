"""
app/services/extraordinary_campaign_service.py

Serviço de Domínio para Gestão de Campanhas Extraordinárias e Templates Reutilizáveis.
Gerencia a criação de campanhas parametrizadas, salvamento de templates, carga de público-alvo
(toda a escola ou turmas selecionadas) e enfileiramento das 20 variações de IA na tabela de mensagens.
"""

from __future__ import annotations

import logging
import uuid
import random
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from app.core.config import settings
from app.infrastructure.supabase.repositories import SupabaseRepository

logger = logging.getLogger(__name__)


class ExtraordinaryCampaignService:
    """
    Serviço que gerencia o ciclo de vida completo de campanhas extraordinárias e seus templates.
    """

    def __init__(self, repository: Optional[SupabaseRepository] = None) -> None:
        self.repo = repository or SupabaseRepository()

    @property
    def client(self):
        return self.repo.client.schema("busca_ativa_v2")

    # ──────────────────────────────────────────────────────────────────────────
    # 0. RISK ENGINE: CALCULADORA DE RISCO ANTI-SPAM (0 A 100)
    # ──────────────────────────────────────────────────────────────────────────
    def calculate_risk_score(
        self,
        *,
        num_variants: int,
        daily_limit: int,
        pilot_mode_active: bool,
        min_delay: int,
        target_count: int,
    ) -> Dict[str, Any]:
        """
        Calcula o Risk Score da campanha de 0 a 100 com base nos fatores de risco da Meta.
        """
        score = 0
        factors = []

        # 1. Diversidade de IA (0-25 pts)
        if num_variants < 5:
            score += 25
            factors.append("🔴 Pouquíssimas variações de IA (< 5)")
        elif num_variants < 20:
            score += 10
            factors.append("🟡 Quantidade moderada de variações de IA (< 20)")
        else:
            factors.append("🟢 Excelente diversidade de IA (20 variações)")

        # 2. Pacing de Delays (0-25 pts)
        if min_delay < 30:
            score += 25
            factors.append("🔴 Delay mínimo muito agressivo (< 30s)")
        elif min_delay < 45:
            score += 12
            factors.append("🟡 Delay mínimo moderado (30s - 45s)")
        else:
            factors.append("🟢 Pacing seguro com delay mínimo >= 45s")

        # 3. Volume vs Aquecimento (0-25 pts)
        if not pilot_mode_active and daily_limit > 100:
            score += 25
            factors.append("🔴 Volume alto (> 100 msgs) sem Modo Piloto")
        elif not pilot_mode_active:
            score += 10
            factors.append("🟡 Disparo direto para turma sem Modo Piloto")
        else:
            factors.append("🟢 Modo Piloto ativado (Disparo fracionado seguro)")

        # 4. Horário e Dia (0-25 pts)
        now = datetime.now()
        if now.weekday() == 6:
            score += 25
            factors.append("🔴 Disparo solicitado no domingo (suspeito)")
        elif now.hour >= 20 or now.hour < 8:
            score += 20
            factors.append("🔴 Disparo solicitado em horário noturno")
        else:
            factors.append("🟢 Disparo dentro do horário comercial seguro")

        risk_level = "SAUDÁVEL (BAIXO)" if score <= 25 else ("MODERADO" if score <= 50 else "ELEVADO (NÃO RECOMENDADO)")
        color = "green" if score <= 25 else ("yellow" if score <= 50 else "red")

        return {
            "score": score,
            "level": risk_level,
            "color": color,
            "factors": factors
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 1. CONSULTA DE TURMAS E PÚBLICO
    # ──────────────────────────────────────────────────────────────────────────
    def list_available_classes(self, school_id: Optional[str] = None) -> List[str]:
        """
        Retorna a lista ordenada de turmas cadastradas na escola.
        """
        try:
            target_school = school_id or settings.default_school_id
            res = (
                self.client.table("students")
                .select("class_name")
                .eq("school_id", target_school)
                .execute()
            )
            classes = sorted(list({r["class_name"] for r in res.data if r.get("class_name")}))
            return classes
        except Exception as exc:
            logger.error(f"Erro ao listar turmas: {exc}")
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # 2. GESTÃO DE TEMPLATES REUTILIZÁVEIS
    # ──────────────────────────────────────────────────────────────────────────
    def save_template(
        self,
        title: str,
        category: str,
        base_message: str,
        target_filter: Dict[str, Any],
        school_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Salva um modelo de campanha reutilizável no banco de dados.
        """
        target_school = school_id or settings.default_school_id
        payload = {
            "school_id": target_school,
            "title": title,
            "category": category,
            "base_message": base_message,
            "target_audience_filter": target_filter,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        res = self.client.table("campaign_templates").insert(payload).execute()
        return res.data[0] if res.data else {}

    def list_templates(self, school_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Lista todos os modelos salvos ordenados por data de criação.
        """
        try:
            target_school = school_id or settings.default_school_id
            res = (
                self.client.table("campaign_templates")
                .select("*")
                .eq("school_id", target_school)
                .order("created_at", desc=True)
                .execute()
            )
            return res.data or []
        except Exception as exc:
            logger.error(f"Erro ao listar templates: {exc}")
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # 3. CRIAÇÃO DE CAMPANHA & GRAVAÇÃO DAS 20 VARIAÇÕES DE IA
    # ──────────────────────────────────────────────────────────────────────────
    def create_campaign(
        self,
        name: str,
        category: str,
        base_message: str,
        target_filter: Dict[str, Any],
        ai_variants: List[str],
        school_id: Optional[str] = None,
        template_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Cria o registro de campanha extraordinária e grava as 20 variações de IA associadas.
        """
        target_school = school_id or settings.default_school_id

        # 1. Inserir registro principal em campaigns
        campaign_payload = {
            "school_id": target_school,
            "name": name,
            "type": "extraordinary",
            "campaign_type": "extraordinary",
            "category": category,
            "base_message": base_message,
            "target_filter": target_filter,
            "class_filter": target_filter.get("classes", []),
            "absence_days": "0",
            "status": "draft",
            "total_sent": 0,
            "total_replied": 0,
            "total_failed": 0,
            "template_id": template_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        res_camp = self.client.table("campaigns").insert(campaign_payload).execute()
        campaign_data = res_camp.data[0]
        campaign_id = campaign_data["id"]

        # 2. Inserir variações na tabela campaign_ai_variants
        variants_payloads = [
            {
                "campaign_id": campaign_id,
                "variant_index": idx + 1,
                "message_text": text,
            }
            for idx, text in enumerate(ai_variants)
        ]

        if variants_payloads:
            self.client.table("campaign_ai_variants").insert(variants_payloads).execute()

        return campaign_data

    # ──────────────────────────────────────────────────────────────────────────
    # 4. CARGA E ENFILEIRAMENTO DE MENSAGENS PENDENTES
    # ──────────────────────────────────────────────────────────────────────────
    def enqueue_campaign_messages(
        self,
        campaign_id: str,
        dry_run: bool = False,
        target_filter: Optional[Dict[str, Any]] = None,
        ai_variants: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Carrega os alunos do público-alvo, distribui as 20 variações de mensagem e enfileira na tabela messages.
        """
        # 1. Buscar campanha e variações
        res_camp = self.client.table("campaigns").select("*").eq("id", campaign_id).single().execute()
        campaign = res_camp.data
        if not campaign:
            raise ValueError(f"Campanha {campaign_id} não encontrada.")

        school_id = campaign["school_id"]
        effective_target_filter = target_filter or campaign.get("target_filter") or {}
        selected_classes = effective_target_filter.get("classes", [])
        all_school = effective_target_filter.get("all_school", False)

        res_vars = (
            self.client.table("campaign_ai_variants")
            .select("variant_index, message_text")
            .eq("campaign_id", campaign_id)
            .order("variant_index")
            .execute()
        )
        variants = (
            [v["message_text"] for v in res_vars.data]
            if res_vars.data
            else (ai_variants or [campaign.get("base_message", "")])
        )

        # 2. Buscar alunos elegíveis
        query = self.client.table("students").select("id, name, class_name").eq("school_id", school_id)
        if not all_school and selected_classes:
            query = query.in_("class_name", selected_classes)

        res_students = query.execute()
        students = res_students.data or []

        if not students:
            return {"total_enqueued": 0, "status": "no_students_found"}

        # 3. Buscar mensagens já existentes nesta campanha (Evita duplicar enfileiramento)
        existing_msgs = (
            self.client.table("messages")
            .select("student_id, guardian_id")
            .eq("campaign_id", campaign_id)
            .execute()
        )
        existing_student_ids = {row["student_id"] for row in (existing_msgs.data or []) if row.get("student_id")}

        # 4. Buscar responsáveis primários (student_guardians -> guardians)
        student_ids = [s["id"] for s in students if s["id"] not in existing_student_ids]
        if not student_ids:
            return {"total_enqueued": 0, "status": "all_already_enqueued"}

        res_sg = (
            self.client.table("student_guardians")
            .select("student_id, guardian_id, is_primary, guardians(id, name, phone_e164, wa_jid)")
            .in_("student_id", student_ids)
            .eq("is_primary", True)
            .execute()
        )

        sg_map = {row["student_id"]: row for row in (res_sg.data or [])}

        messages_to_insert = []
        now_str = datetime.now(timezone.utc).isoformat()

        for idx, student in enumerate(students):
            student_id = student["id"]
            sg_data = sg_map.get(student_id)

            if not sg_data or not sg_data.get("guardians"):
                continue

            guardian = sg_data["guardians"]
            guardian_id = guardian["id"]
            phone = (guardian.get("phone_e164") or guardian.get("wa_jid") or "").strip()

            if not phone:
                continue

            # Seleciona uma das 20 variações por round-robin para distribuição uniforme
            variant_text = variants[idx % len(variants)]

            # Formata os placeholders na mensagem da variação escolhida
            parent_name = guardian.get("name") or "Responsável"
            student_name = student.get("name") or "Aluno"
            class_name = student.get("class_name") or ""
            school_name = settings.school_name

            formatted_body = (
                variant_text.replace("{{nome_responsavel}}", parent_name)
                .replace("{{nome_aluno}}", student_name)
                .replace("{{turma}}", class_name)
                .replace("{{escola}}", school_name)
            )

            tracking_ref = f"EXT-{campaign_id[:8]}-{student_id[:8]}"
            wa_jid = f"{phone}@s.whatsapp.net" if not phone.endswith("@s.whatsapp.net") else phone

            messages_to_insert.append(
                {
                    "school_id": school_id,
                    "campaign_id": campaign_id,
                    "student_id": student_id,
                    "guardian_id": guardian_id,
                    "tracking_ref": tracking_ref,
                    "wa_jid": wa_jid,
                    "template_id": f"variant_{ (idx % len(variants)) + 1 }",
                    "body_preview": formatted_body,
                    "status": "pending",
                    "created_at": now_str,
                    "updated_at": now_str,
                    "metadata": {
                        "campaign_type": "extraordinary",
                        "variant_index": (idx % len(variants)) + 1,
                        "formatted_body": formatted_body,
                        "skip_justification_suffix": True,
                        "dry_run": dry_run,
                    },
                }
            )

        if not dry_run and messages_to_insert:
            # Insere em lotes de 100 mensagens para evitar payload excessivo no Supabase
            batch_size = 100
            for i in range(0, len(messages_to_insert), batch_size):
                batch = messages_to_insert[i : i + batch_size]
                self.client.table("messages").insert(batch).execute()

            # Atualiza status da campanha para 'pending'
            self.client.table("campaigns").update({"status": "pending"}).eq("id", campaign_id).execute()

        return {
            "total_students": len(students),
            "total_enqueued": len(messages_to_insert),
            "total_variants_used": len(variants),
            "dry_run": dry_run,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 5. MÉTRICAS E HISTÓRICO DAS CAMPANHAS
    # ──────────────────────────────────────────────────────────────────────────
    def list_all_campaigns(self, school_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retorna todas as campanhas realizadas (Busca Ativa, OBMEP e Extraordinárias).
        """
        try:
            target_school = school_id or settings.default_school_id
            res = (
                self.client.table("campaigns")
                .select("*")
                .eq("school_id", target_school)
                .order("created_at", desc=True)
                .execute()
            )
            return res.data or []
        except Exception as exc:
            logger.error(f"Erro ao listar campanhas: {exc}")
            return []

    def get_campaign_details(self, campaign_id: str) -> Dict[str, Any]:
        """
        Retorna os detalhes completos de uma campanha com suas variações e estatísticas.
        """
        # Detalhes da campanha
        res_camp = self.client.table("campaigns").select("*").eq("id", campaign_id).single().execute()
        campaign = res_camp.data or {}

        # Variações de IA
        res_vars = (
            self.client.table("campaign_ai_variants")
            .select("variant_index, message_text")
            .eq("campaign_id", campaign_id)
            .order("variant_index")
            .execute()
        )

        # Contagem de mensagens por status
        res_msgs = (
            self.client.table("messages")
            .select("status")
            .eq("campaign_id", campaign_id)
            .execute()
        )

        counts = {"pending": 0, "sent": 0, "delivered": 0, "read": 0, "failed": 0, "replied": 0}
        total_msgs = 0
        if res_msgs.data:
            for row in res_msgs.data:
                st = row.get("status")
                if st in counts:
                    counts[st] += 1
                total_msgs += 1

        campaign["ai_variants"] = [v["message_text"] for v in (res_vars.data or [])]
        campaign["stats"] = counts
        campaign["total_messages"] = total_msgs

        return campaign
