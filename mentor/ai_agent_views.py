from pathlib import Path
import json
import queue
import threading
import os
import re


from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.files.storage import FileSystemStorage
from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import StreamingHttpResponse, HttpResponse, JsonResponse
from django.db import close_old_connections, transaction, models
from django.utils.text import get_valid_filename
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
import secrets
from mentor.ai_agent_models import (

    AnalysisKnowledge,
    KnowledgeSource,
    KnowledgeChunk,
    KnowledgeItem,
    Organization,
    GenericKnowledge,
    GenericKnowledgeItem,
    GenericKnowledgeCandidate,
    TermCandidate,
)
from mentor.services.analysis_service import analyze_question
from mentor.services.generic_knowledge_service import get_generic_answer
from mentor.services.external_ai_service import ask_external_ai
from mentor.services.api_service import get_alpaca_latest_trade, get_alpaca_recent_bars
from mentor.services.reset_service import reset_knowledge_base
from mentor.services.source_ingestion import ingest_file
from mentor.services.generic_knowledge_promotion_service import (
    promote_generic_knowledge_candidate,
)
from mentor.services.pending_knowledge_consolidation_service import (
    analyze_pending_generic_knowledge,
    apply_pending_generic_knowledge_consolidation,
)


def user_has_ai_access(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name='GRP_AIAgent').exists()


def user_is_ai_admin(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name='GRP_AIAgent_Admin').exists()


@login_required
def dashboard(request):
    if not user_is_ai_admin(request.user):
        return render(request, 'ai_agent/access_denied.html', status=403)

    groups = list(request.user.groups.values_list('name', flat=True))

    context = {
        'groups': groups,
        'is_ai_admin': request.user.is_superuser or 'GRP_AIAgent_Admin' in groups,
        'is_standard_user': 'GRP_AIAgent_User' in groups,
        'is_readonly': 'GRP_AIAgent_ReadOnly' in groups,
        'knowledge_sources_count': KnowledgeSource.objects.filter(is_active=True).count(),
        'knowledge_chunks_count': KnowledgeChunk.objects.filter(source__is_active=True).count(),
        'generic_knowledge_count': GenericKnowledge.objects.filter(is_active=True).count(),
        'generic_knowledge_items_count': GenericKnowledgeItem.objects.filter(
            is_active=True,
            generic_knowledge__is_active=True,
        ).count(),
        'pending_generic_candidates_count': GenericKnowledgeCandidate.objects.filter(
            status='PENDING'
        ).count(),
        'analysis_knowledge_count': AnalysisKnowledge.objects.filter(is_active=True).count(),
        'organizations_count': Organization.objects.filter(is_active=True).count(),
        'knowledge_sources': KnowledgeSource.objects.filter(
            is_active=True
        ).select_related('organization').order_by('-created_at')[:10],
    }
    return render(request, 'ai_agent/ai_dashboard.html', context)


@login_required
def upload_information(request):
    if not user_is_ai_admin(request.user):
        return render(request, 'ai_agent/access_denied.html', status=403)

    groups = list(request.user.groups.values_list('name', flat=True))
    if 'GRP_AIAgent_ReadOnly' in groups and not user_is_ai_admin(request.user):
        return render(request, 'ai_agent/access_denied.html', status=403)

    default_org = Organization.objects.filter(
        is_active=True, is_default=True
    ).first()

    organizations = Organization.objects.filter(
        is_active=True
    ).order_by('-is_default', 'name')

    requested_organization_id = (request.GET.get('organization') or '').strip()

    context = {
        'organizations': organizations,
        'default_organization_id': default_org.id if default_org else '',
        'selected_organization_id': requested_organization_id,
        'error': '',
    }

    if request.method == 'POST':
        organization_id = (request.POST.get('organization') or '').strip()
        source_name = (request.POST.get('source_name') or '').strip()
        uploaded_files = request.FILES.getlist('information_file')

        try:
            if not organization_id:
                raise ValueError('Please select a customer / organization.')

            organization = Organization.objects.get(
                pk=organization_id,
                is_active=True,
            )

            if not uploaded_files:
                raise ValueError('Please choose one or more files to upload.')

            upload_root = Path(settings.BASE_DIR) / 'Knowledge_Inbox'
            customer_folder = get_valid_filename(organization.name) or f'organization_{organization.id}'
            target_dir = upload_root / customer_folder
            target_dir.mkdir(parents=True, exist_ok=True)
            storage = FileSystemStorage(location=str(target_dir))

            successful_files = []
            failed_files = []
            total_chunks = 0
            multiple_files = len(uploaded_files) > 1

            for uploaded_file in uploaded_files:
                safe_name = get_valid_filename(Path(uploaded_file.name).name)

                if not safe_name:
                    failed_files.append({
                        'name': uploaded_file.name or 'Unnamed file',
                        'error': 'The uploaded filename is not valid.',
                    })
                    continue

                stored_name = None

                try:
                    stored_name = storage.save(safe_name, uploaded_file)
                    stored_path = target_dir / stored_name

                    # A custom Source Name is meaningful for a single upload only.
                    # For a batch, each document keeps its own filename-based identity.
                    effective_source_name = (
                        source_name
                        if source_name and not multiple_files
                        else Path(safe_name).stem
                    )

                    result = ingest_file(
                        file_path=stored_path,
                        source_name=effective_source_name,
                        organization=organization,
                        created_by=request.user,
                    )

                    stored_chunks = int(result.get('stored_chunks', 0) or 0)
                    total_chunks += stored_chunks
                    successful_files.append({
                        'name': safe_name,
                        'stored_chunks': stored_chunks,
                    })

                except Exception as exc:
                    if stored_name and storage.exists(stored_name):
                        storage.delete(stored_name)

                    failed_files.append({
                        'name': safe_name,
                        'error': str(exc),
                    })

            if successful_files:
                messages.success(
                    request,
                    f"{len(successful_files)} file(s) processed successfully for "
                    f"{organization.name}. {total_chunks} searchable content record(s) "
                    "stored. OpenAI was not used."
                )

            if failed_files:
                failed_summary = "; ".join(
                    f"{item['name']}: {item['error']}"
                    for item in failed_files
                )
                messages.warning(
                    request,
                    f"{len(failed_files)} file(s) failed while the other files were kept. "
                    f"{failed_summary}"
                )

            if successful_files:
                # Stay on the Upload Information page so the user can immediately
                # ask Internal Knowledge about the selected organization.
                return redirect(f"{request.path}?organization={organization.id}&uploaded=1")

            raise ValueError(
                "No files were processed successfully. "
                + "; ".join(
                    f"{item['name']}: {item['error']}"
                    for item in failed_files
                )
            )

        except Organization.DoesNotExist:
            context['error'] = 'The selected customer / organization is not valid.'
        except Exception as exc:
            context['error'] = str(exc)

        context['selected_organization_id'] = organization_id
        context['source_name'] = source_name

    return render(request, 'ai_agent/upload_information.html', context)



def _delete_customer_source(source):
    """Delete one uploaded source and its source-specific local artifacts."""
    source_id = source.pk
    source_reference = (source.source_reference or '').strip()

    # TermCandidate is not a ForeignKey to KnowledgeSource. Ingestion records
    # provenance as "KnowledgeSource:<id>", so remove only candidates created
    # specifically from this source.
    TermCandidate.objects.filter(
        source_reference=f"KnowledgeSource:{source_id}"
    ).delete()

    # KnowledgeChunk rows are deleted automatically because KnowledgeChunk.source
    # uses on_delete=CASCADE.
    source.delete()

    # Remove the physical uploaded file only when it is safely inside
    # Knowledge_Inbox. Database cleanup remains valid even if the file is already
    # absent from disk.
    if source_reference:
        try:
            upload_root = (Path(settings.BASE_DIR) / 'Knowledge_Inbox').resolve()
            file_path = Path(source_reference).resolve()
            if upload_root == file_path or upload_root in file_path.parents:
                if file_path.is_file():
                    file_path.unlink()
        except (OSError, RuntimeError, ValueError):
            pass


@login_required
def customer_sources(request):
    if not user_is_ai_admin(request.user):
        return render(request, 'ai_agent/access_denied.html', status=403)

    groups = list(request.user.groups.values_list('name', flat=True))
    if 'GRP_AIAgent_ReadOnly' in groups and not user_is_ai_admin(request.user):
        return render(request, 'ai_agent/access_denied.html', status=403)

    organizations = Organization.objects.filter(is_active=True).order_by(
        '-is_default', 'name'
    )
    organization_id = (
        request.POST.get('organization')
        or request.GET.get('organization')
        or ''
    ).strip()

    organization = None
    sources = KnowledgeSource.objects.none()

    if organization_id:
        organization = Organization.objects.filter(
            pk=organization_id,
            is_active=True,
        ).first()
        if organization:
            sources = KnowledgeSource.objects.filter(
                organization=organization,
                source_type='FILE',
            ).annotate(
                chunk_count=models.Count('chunks')
            ).order_by('-created_at')

    if request.method == 'POST':
        if not organization:
            messages.error(request, 'Please select a valid customer / organization.')
            return redirect('customer_sources')

        action = (request.POST.get('action') or '').strip()
        selected_ids = request.POST.getlist('source_ids')

        if action == 'delete_selected':
            selected_sources = list(
                KnowledgeSource.objects.filter(
                    organization=organization,
                    source_type='FILE',
                    pk__in=selected_ids,
                )
            )
            if not selected_sources:
                messages.warning(request, 'Please select at least one file to delete.')
            else:
                with transaction.atomic():
                    for source in selected_sources:
                        _delete_customer_source(source)
                messages.success(
                    request,
                    f'{len(selected_sources)} file(s) deleted for {organization.name}.'
                )

        elif action == 'delete_all':
            all_sources = list(
                KnowledgeSource.objects.filter(
                    organization=organization,
                    source_type='FILE',
                )
            )
            if not all_sources:
                messages.info(request, f'No uploaded files exist for {organization.name}.')
            else:
                with transaction.atomic():
                    for source in all_sources:
                        _delete_customer_source(source)
                messages.success(
                    request,
                    f'All {len(all_sources)} uploaded file(s) deleted for {organization.name}.'
                )
        else:
            messages.error(request, 'Invalid delete action.')

        return redirect(f"{reverse('customer_sources')}?organization={organization.id}")

    return render(request, 'ai_agent/customer_sources.html', {
        'organizations': organizations,
        'organization': organization,
        'selected_organization_id': organization_id,
        'sources': sources,
    })


@login_required
def add_customer(request):
    if not user_is_ai_admin(request.user):
        return render(request, 'ai_agent/access_denied.html', status=403)

    groups = list(request.user.groups.values_list('name', flat=True))
    if 'GRP_AIAgent_ReadOnly' in groups and not user_is_ai_admin(request.user):
        return render(request, 'ai_agent/access_denied.html', status=403)

    context = {
        'error': '',
        'customer_name': '',
    }

    if request.method == 'POST':
        customer_name = (request.POST.get('customer_name') or '').strip()
        context['customer_name'] = customer_name

        if not customer_name:
            context['error'] = 'Customer name is required.'
        else:
            existing = Organization.objects.filter(
                name__iexact=customer_name
            ).first()

            if existing:
                if not existing.is_active:
                    existing.is_active = True
                    existing.organization_type = 'CUSTOMER'
                    existing.save(
                        update_fields=[
                            'is_active',
                            'organization_type',
                            'updated_at',
                        ]
                    )

                messages.info(
                    request,
                    f'{existing.name} already exists and is available for selection.'
                )
                return redirect(f"/upload/?organization={existing.id}")

            organization = Organization.objects.create(
                name=customer_name,
                organization_type='CUSTOMER',
                is_default=False,
                is_active=True,
            )

            messages.success(
                request,
                f'Customer {organization.name} added successfully.'
            )
            return redirect(f"/upload/?organization={organization.id}")

    return render(request, 'ai_agent/add_customer.html', context)


def ask_ai_agent(request):
    # Public AI-Agent entry point. Administrative/customer knowledge functions
    # remain protected separately.
    organizations = Organization.objects.filter(is_active=True).order_by(
        '-is_default', 'name'
    )
    default_org = organizations.filter(is_default=True).first()

    question = ''
    answer = ''
    external_answer = ''
    external_model = ''
    external_openai_used = None
    external_source_type = ''
    external_openai_usage_type = ''
    selected_ai_provider = 'openai'

    # Generic Knowledge source traceability
    external_interpretation_source = ''
    external_database_searched = False
    external_database_match_found = False
    external_knowledge_source = ''
    external_answer_information_source = ''
    external_openai_interpretation_used = False
    external_openai_knowledge_used = False
    external_openai_external_lookup_performed = False

    # Matching evidence for interpreted Generic Knowledge retrieval
    external_interpreted_concept = ''
    external_interpreted_aspect = ''
    external_matched_concept = ''
    external_matched_aspect = ''
    external_concept_semantic_score = None
    external_aspect_semantic_score = None
    external_interpretation_semantic_score = None
    external_generic_knowledge_id = None

    answer_mode = ''
    sources = []
    retrieved_items = 0
    retrieved_chunks = 0
    error = ''
    selected_organization_id = (
        request.POST.get('organization')
        if request.method == 'POST'
        else (default_org.id if default_org else '')
    )
    selected_source_ids = (
        [value.strip() for value in request.POST.getlist('source_ids') if value.strip()]
        if request.method == 'POST'
        else []
    )
    selected_source_id = selected_source_ids[0] if len(selected_source_ids) == 1 else ''

    if request.method == 'POST':
        organization_change = request.POST.get('organization_change') == '1'
        action = (request.POST.get('action') or 'internal').strip()
        question = (request.POST.get('question') or '').strip()
        selected_ai_provider = (request.POST.get('ai_provider') or 'openai').strip().lower()
        if selected_ai_provider not in {'openai', 'copilot'}:
            selected_ai_provider = 'openai' 

        try:
            organization = Organization.objects.get(
                id=selected_organization_id,
                is_active=True,
            )
        except (Organization.DoesNotExist, ValueError, TypeError):
            organization = None
            error = 'Please select a valid Customer / Organization.'

        if not organization_change and not question:
            error = 'Question is required.'

        selected_sources = []
        if not error and selected_source_ids:
            selected_sources = list(KnowledgeSource.objects.filter(
                id__in=selected_source_ids, organization=organization, is_active=True
            ))
            if len(selected_sources) != len(set(selected_source_ids)):
                error = 'Please select valid documents for the selected organization.'

        if not error and not organization_change:
            try:
                if action == 'external':
                    if selected_ai_provider == 'copilot':
                        raise ValueError(
                            'Microsoft Copilot is selected, but the Copilot Studio connection '
                            'is pending administrator activation. OpenAI was not used.'
                        )
                    result = get_generic_answer(
                        question,
                        user=request.user,
                    )
                    result['ai_provider'] = 'OPENAI' 
                    external_answer = result.get('answer', '')
                    external_model = result.get('model', '')
                    external_openai_used = result.get('openai_used', False)
                    external_source_type = result.get('source_type', '')
                    external_openai_usage_type = result.get('openai_usage_type', '')

                    # Keep interpretation source separate from answer-information source.
                    external_interpretation_source = result.get(
                        'interpretation_source', ''
                    )
                    external_database_searched = result.get(
                        'database_searched', False
                    )
                    external_database_match_found = result.get(
                        'database_match_found', False
                    )
                    external_knowledge_source = result.get(
                        'knowledge_source', ''
                    )
                    external_answer_information_source = result.get(
                        'answer_information_source', ''
                    )
                    external_openai_interpretation_used = result.get(
                        'openai_interpretation_used', False
                    )
                    external_openai_knowledge_used = result.get(
                        'openai_knowledge_used', False
                    )
                    external_openai_external_lookup_performed = result.get(
                        'openai_external_lookup_performed', False
                    )

                    # Matching evidence: what OpenAI/local interpretation produced
                    # and which Generic Knowledge item was selected locally.
                    interpretation = result.get('interpretation') or {}
                    external_interpreted_concept = interpretation.get(
                        'canonical_concept', ''
                    )
                    external_interpreted_aspect = interpretation.get(
                        'knowledge_aspect', ''
                    )
                    external_matched_concept = result.get('matched_concept', '')
                    external_matched_aspect = result.get('matched_aspect', '')
                    external_concept_semantic_score = result.get(
                        'concept_semantic_score'
                    )
                    external_aspect_semantic_score = result.get(
                        'aspect_semantic_score'
                    )
                    external_interpretation_semantic_score = result.get(
                        'interpretation_semantic_score'
                    )
                    external_generic_knowledge_id = result.get(
                        'generic_knowledge_id'
                    )

                    answer_mode = 'external'
                else:
                    result = analyze_question(
                        question,
                        organization_id=organization.id,
                        source_ids=[source.id for source in selected_sources] or None,
                    )
                    answer = result.get('answer', '')
                    sources = result.get('sources', [])
                    retrieved_items = result.get('retrieved_items', 0)
                    retrieved_chunks = result.get('retrieved_chunks', 0)
                    answer_mode = 'internal'
            except Exception as exc:
                error = str(exc)

    knowledge_sources = KnowledgeSource.objects.filter(
        is_active=True,
        organization_id=selected_organization_id,
    ).order_by('name') if selected_organization_id else KnowledgeSource.objects.none()

    context = {
        'organizations': organizations,
        'selected_organization_id': selected_organization_id,
        'knowledge_sources': knowledge_sources,
        'selected_source_id': selected_source_id,
        'selected_source_ids': selected_source_ids,
        'question': question,
        'answer': answer,
        'external_answer': external_answer,
        'external_model': external_model,
        'external_openai_used': external_openai_used,
        'external_source_type': external_source_type,
        'external_openai_usage_type': external_openai_usage_type,
        'selected_ai_provider': selected_ai_provider,
        'external_interpretation_source': external_interpretation_source,
        'external_database_searched': external_database_searched,
        'external_database_match_found': external_database_match_found,
        'external_knowledge_source': external_knowledge_source,
        'external_answer_information_source': external_answer_information_source,
        'external_openai_interpretation_used': external_openai_interpretation_used,
        'external_openai_knowledge_used': external_openai_knowledge_used,
        'external_openai_external_lookup_performed': external_openai_external_lookup_performed,
        'external_interpreted_concept': external_interpreted_concept,
        'external_interpreted_aspect': external_interpreted_aspect,
        'external_matched_concept': external_matched_concept,
        'external_matched_aspect': external_matched_aspect,
        'external_concept_semantic_score': external_concept_semantic_score,
        'external_aspect_semantic_score': external_aspect_semantic_score,
        'external_interpretation_semantic_score': external_interpretation_semantic_score,
        'external_generic_knowledge_id': external_generic_knowledge_id,
        'answer_mode': answer_mode,
        'sources': sources,
        'retrieved_items': retrieved_items,
        'retrieved_chunks': retrieved_chunks,
        'error': error,
    }
    return render(request, 'ai_agent/ask_ai_agent.html', context)


@login_required
def internal_knowledge_progress(request):
    """
    Stream real Internal / Customer Knowledge processing stages as NDJSON.

    This workflow retrieves customer evidence from the local AI-Agent database,
    then uses OpenAI for question interpretation and analysis of the selected evidence.
    Customer-specific facts remain bounded by the retrieved Internal Knowledge.
    """
    if not user_has_ai_access(request.user):
        return StreamingHttpResponse(
            iter([json.dumps({"type": "error", "message": "Access denied."}) + "\n"]),
            content_type="application/x-ndjson",
            status=403,
        )

    if request.method != "POST":
        return StreamingHttpResponse(
            iter([json.dumps({"type": "error", "message": "POST required."}) + "\n"]),
            content_type="application/x-ndjson",
            status=405,
        )

    question = (request.POST.get("question") or "").strip()
    organization_id = (request.POST.get("organization") or "").strip()
    source_ids = [value.strip() for value in request.POST.getlist("source_ids") if value.strip()]

    if not question:
        return StreamingHttpResponse(
            iter([json.dumps({"type": "error", "message": "Question is required."}) + "\n"]),
            content_type="application/x-ndjson",
            status=400,
        )

    try:
        organization = Organization.objects.get(
            id=organization_id,
            is_active=True,
        )
    except (Organization.DoesNotExist, ValueError, TypeError):
        return StreamingHttpResponse(
            iter([json.dumps({"type": "error", "message": "Please select a valid Customer / Organization."}) + "\n"]),
            content_type="application/x-ndjson",
            status=400,
        )

    selected_sources = []
    if source_ids:
        selected_sources = list(KnowledgeSource.objects.filter(
            id__in=source_ids, organization=organization, is_active=True
        ))
        if len(selected_sources) != len(set(source_ids)):
            return StreamingHttpResponse(
                iter([json.dumps({"type": "error", "message": "Please select valid documents for the selected organization."}) + "\n"]),
                content_type="application/x-ndjson", status=400,
            )

    event_queue = queue.Queue()

    def _safe_text(value):
        """Normalize structured AI values before storing Pending Internal Knowledge."""
        if value is None:
            return ""
        if isinstance(value, (list, tuple, set)):
            return "\n".join(
                _safe_text(item)
                for item in value
                if _safe_text(item)
            )
        if isinstance(value, dict):
            return "\n".join(
                f"{key}: {_safe_text(item)}"
                for key, item in value.items()
                if _safe_text(item)
            )
        return str(value).strip()

    def progress_callback(percent, stage):
        event_queue.put({
            "type": "progress",
            "percent": int(percent),
            "stage": stage,
        })

    def worker():
        close_old_connections()
        try:
            result = analyze_question(
                question,
                organization_id=organization.id,
                source_ids=[source.id for source in selected_sources] or None,
                progress_callback=progress_callback,
            )
            result["organization_name"] = organization.name
            result["document_name"] = (
                ", ".join(source.name for source in selected_sources)
                if selected_sources else "All documents for this organization"
            )

            # Store the generated customer-specific analysis as Pending Validation.
            # It becomes trusted Internal Knowledge only after the user selects Proceed.
            analysis_content_parts = [
                "QUESTION\n" + question,
                "CUSTOMER / INTERNAL INFORMATION\n" + (result.get("answer", "").split("\n\nADDITIONAL / MISSING INFORMATION", 1)[0].replace("CUSTOMER / INTERNAL INFORMATION\n", "", 1).strip()),
            ]
            assessed_aspects = ((result.get("evidence_assessment") or {}).get("aspects") or [])
            if assessed_aspects:
                gap_lines = []
                for assessed in assessed_aspects:
                    status = (assessed.get("status") or "").strip().upper()
                    if status in {"PARTIAL", "NOT_FOUND"}:
                        gap_lines.append(
                            f"{_safe_text(assessed.get('aspect'))} | {status} | "
                            f"{_safe_text(assessed.get('missing_information'))}"
                        )
                if gap_lines:
                    analysis_content_parts.append("GAPS / INFORMATION REQUIRING CONFIRMATION\n" + "\n".join(gap_lines))

            if result.get("recommended_approach"):
                analysis_content_parts.append(
                    "RECOMMENDED APPROACH\n" + _safe_text(result.get("recommended_approach"))
                )

            pending_analysis = AnalysisKnowledge.objects.create(
                organization=organization,
                title=("AI-Agent Analysis - " + question)[:255],
                content="\n\n".join(analysis_content_parts),
                origin_type="INTERNAL",
                validation_status="PENDING",
                created_by=request.user,
                is_active=True,
            )

            evidence_source_ids = {
                source.get("source_id")
                for source in (result.get("sources") or [])
                if source.get("source_id")
            }
            evidence_source_ids.update(source.id for source in selected_sources)
            if evidence_source_ids:
                pending_analysis.evidence_sources.set(
                    KnowledgeSource.objects.filter(
                        id__in=evidence_source_ids,
                        organization=organization,
                        is_active=True,
                    )
                )

            result["pending_analysis_id"] = pending_analysis.id
            result["pending_analysis_status"] = pending_analysis.validation_status

            event_queue.put({
                "type": "progress",
                "percent": 100,
                "stage": (
                    "Internal Knowledge completed - OpenAI interpretation and customer-evidence analysis used; customer facts source: Internal Database"
                    if result.get("openai_interpretation_used")
                    else "Internal Knowledge analysis completed - OpenAI API Used: NO"
                ),
            })
            event_queue.put({"type": "result", "result": result})
        except Exception as exc:
            event_queue.put({"type": "error", "message": str(exc)})
        finally:
            close_old_connections()
            event_queue.put({"type": "done"})

    def event_stream():
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        while True:
            event = event_queue.get()
            yield json.dumps(event, default=str) + "\n"
            if event.get("type") == "done":
                break

    response = StreamingHttpResponse(
        event_stream(),
        content_type="application/x-ndjson",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
def review_internal_analysis(request):
    """Proceed (validate) or Reject a Pending customer-specific analysis."""
    if not user_has_ai_access(request.user):
        return StreamingHttpResponse(
            iter([json.dumps({"ok": False, "message": "Access denied."}) + "\n"]),
            content_type="application/json",
            status=403,
        )

    if request.method != "POST":
        return StreamingHttpResponse(
            iter([json.dumps({"ok": False, "message": "POST required."}) + "\n"]),
            content_type="application/json",
            status=405,
        )

    analysis_id = (request.POST.get("analysis_id") or "").strip()
    decision = (request.POST.get("decision") or "").strip().upper()
    if decision not in {"PROCEED", "REJECT"}:
        return StreamingHttpResponse(
            iter([json.dumps({"ok": False, "message": "Decision must be PROCEED or REJECT."}) + "\n"]),
            content_type="application/json",
            status=400,
        )

    try:
        analysis = AnalysisKnowledge.objects.get(id=analysis_id, is_active=True)
    except (AnalysisKnowledge.DoesNotExist, ValueError, TypeError):
        return StreamingHttpResponse(
            iter([json.dumps({"ok": False, "message": "Analysis record not found."}) + "\n"]),
            content_type="application/json",
            status=404,
        )

    if analysis.validation_status != "PENDING":
        return StreamingHttpResponse(
            iter([json.dumps({
                "ok": False,
                "message": "This analysis has already been reviewed.",
                "status": analysis.validation_status,
            }) + "\n"]),
            content_type="application/json",
            status=409,
        )

    analysis.validation_status = "VALIDATED" if decision == "PROCEED" else "REJECTED"
    analysis.save(update_fields=["validation_status", "updated_at"])

    return StreamingHttpResponse(
        iter([json.dumps({
            "ok": True,
            "analysis_id": analysis.id,
            "status": analysis.validation_status,
            "message": (
                "Analysis validated and available as trusted Internal Knowledge."
                if analysis.validation_status == "VALIDATED"
                else "Analysis rejected and will not be treated as validated Internal Knowledge."
            ),
        }) + "\n"]),
        content_type="application/json",
    )



@login_required
def export_internal_analysis_docx(request, analysis_id):
    """Export one customer-specific AI-Agent analysis as an editable Word document."""
    if not user_has_ai_access(request.user):
        return HttpResponse("Access denied.", status=403)

    try:
        analysis = AnalysisKnowledge.objects.select_related("organization").prefetch_related("evidence_sources").get(
            id=analysis_id,
            is_active=True,
        )
    except AnalysisKnowledge.DoesNotExist:
        return HttpResponse("Analysis record not found.", status=404)

    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
        from docx.shared import Inches, Pt, RGBColor
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
    except ImportError:
        return HttpResponse(
            "Word export requires python-docx. Install it with: pip install python-docx",
            status=500,
        )

    def split_sections(content):
        headings = {
            "QUESTION",
            "CUSTOMER / INTERNAL INFORMATION",
            "GAPS / INFORMATION REQUIRING CONFIRMATION",
            "RECOMMENDED APPROACH",
        }
        result = {}
        current = None
        lines = (content or "").splitlines()
        for line in lines:
            stripped = line.strip()
            if stripped in headings:
                current = stripped
                result.setdefault(current, [])
            elif current is not None:
                result[current].append(line)
        return {k: "\n".join(v).strip() for k, v in result.items()}

    def shade_cell(cell, fill):
        tc_pr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:fill"), fill)
        tc_pr.append(shd)

    sections = split_sections(analysis.content)
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.65)
    section.left_margin = Inches(0.7)
    section.right_margin = Inches(0.7)

    styles = doc.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"].font.size = Pt(10)
    for style_name in ("Title", "Heading 1", "Heading 2"):
        styles[style_name].font.name = "Aptos Display"
        styles[style_name].font.color.rgb = RGBColor(31, 78, 121)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("AI-AGENT INTERNAL KNOWLEDGE ANALYSIS")
    run.bold = True
    run.font.size = Pt(18)
    run.font.color.rgb = RGBColor(31, 78, 121)

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = subtitle.add_run(analysis.organization.name)
    r.bold = True
    r.font.size = Pt(12)

    meta = doc.add_table(rows=3, cols=2)
    meta.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta.style = "Table Grid"
    meta_data = [
        ("Knowledge Status", analysis.validation_status),
        ("Origin", "Customer-specific Internal Analysis"),
        ("Created", analysis.created_at.strftime("%d/%m/%Y %H:%M") if analysis.created_at else ""),
    ]
    for row, (label, value) in zip(meta.rows, meta_data):
        row.cells[0].text = label
        row.cells[1].text = value
        shade_cell(row.cells[0], "D9EAF7")
        row.cells[0].paragraphs[0].runs[0].bold = True
        for cell in row.cells:
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    doc.add_heading("1. Question / Objective", level=1)
    doc.add_paragraph(sections.get("QUESTION") or analysis.title)

    customer_text = sections.get("CUSTOMER / INTERNAL INFORMATION", "")
    doc.add_heading("2. Executive Summary", level=1)
    sentences = [x.strip() for x in customer_text.replace("\n", " ").split(". ") if x.strip()]
    summary = ". ".join(sentences[:3])
    if summary and not summary.endswith("."):
        summary += "."
    doc.add_paragraph(summary or "Customer evidence analysis is available below.")

    doc.add_heading("3. Customer / Internal Information", level=1)
    for paragraph in [x.strip() for x in customer_text.split("\n") if x.strip()] or [customer_text]:
        doc.add_paragraph(paragraph)

    gaps = sections.get("GAPS / INFORMATION REQUIRING CONFIRMATION", "")
    doc.add_heading("4. Gaps / Information Requiring Confirmation", level=1)
    if gaps:
        rows = [x for x in gaps.splitlines() if x.strip()]
        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        headers = ["Area", "Status", "Information Required"]
        for i, header in enumerate(headers):
            table.rows[0].cells[i].text = header
            shade_cell(table.rows[0].cells[i], "1F4E79")
            run = table.rows[0].cells[i].paragraphs[0].runs[0]
            run.bold = True
            run.font.color.rgb = RGBColor(255, 255, 255)
        for line in rows:
            parts = [x.strip() for x in line.split("|", 2)]
            while len(parts) < 3:
                parts.append("")
            cells = table.add_row().cells
            for i, value in enumerate(parts[:3]):
                cells[i].text = value
            if parts[1] == "PARTIAL":
                shade_cell(cells[1], "FFF2CC")
            elif parts[1] == "NOT_FOUND":
                shade_cell(cells[1], "F4CCCC")
    else:
        doc.add_paragraph("No unresolved information gaps were stored with this analysis.")

    doc.add_heading("5. Recommended Approach", level=1)
    note = doc.add_paragraph()
    rr = note.add_run("AI-Agent recommendation - not customer-provided information.")
    rr.bold = True
    rr.italic = True
    rr.font.color.rgb = RGBColor(31, 78, 121)
    recommendation = sections.get("RECOMMENDED APPROACH", "")
    for line in [x.strip() for x in recommendation.splitlines() if x.strip()] or ["No recommendation was generated."]:
        doc.add_paragraph(line)

    doc.add_heading("6. Evidence / Sources", level=1)
    sources = list(analysis.evidence_sources.filter(is_active=True).order_by("name"))
    if sources:
        for source in sources:
            doc.add_paragraph(source.name, style="List Bullet")
    else:
        doc.add_paragraph("No evidence-source links are attached to this analysis record.")

    doc.add_heading("7. Knowledge Validation", level=1)
    doc.add_paragraph(
        "This document reflects the AI-Agent analysis record and its current validation status. "
        "Customer facts are derived from linked Internal Knowledge evidence; recommendations are AI-Agent guidance."
    )

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("Generated by AI-Agent | Internal Working Document").font.size = Pt(8)

    from io import BytesIO
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    filename = get_valid_filename(f"AI-Agent_{analysis.organization.name}_{analysis.id}.docx")
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def export_internal_analysis_pdf(request, analysis_id):
    """Export one customer-specific AI-Agent analysis as a professional PDF report."""
    if not user_has_ai_access(request.user):
        return HttpResponse("Access denied.", status=403)

    try:
        analysis = AnalysisKnowledge.objects.select_related("organization").prefetch_related("evidence_sources").get(
            id=analysis_id,
            is_active=True,
        )
    except AnalysisKnowledge.DoesNotExist:
        return HttpResponse("Analysis record not found.", status=404)

    try:
        from io import BytesIO
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        )
    except ImportError:
        return HttpResponse(
            "PDF export requires reportlab. Install it with: pip install reportlab",
            status=500,
        )

    def split_sections(content):
        headings = {
            "QUESTION",
            "CUSTOMER / INTERNAL INFORMATION",
            "GAPS / INFORMATION REQUIRING CONFIRMATION",
            "RECOMMENDED APPROACH",
        }
        result = {}
        current = None
        for line in (content or "").splitlines():
            stripped = line.strip()
            if stripped in headings:
                current = stripped
                result.setdefault(current, [])
            elif current is not None:
                result[current].append(line)
        return {k: "\n".join(v).strip() for k, v in result.items()}

    def safe(text):
        import html
        return html.escape(str(text or "")).replace("\n", "<br/>")

    sections = split_sections(analysis.content)
    customer_text = sections.get("CUSTOMER / INTERNAL INFORMATION", "")
    gaps = sections.get("GAPS / INFORMATION REQUIRING CONFIRMATION", "")
    recommendation = sections.get("RECOMMENDED APPROACH", "")

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=16*mm, leftMargin=16*mm, topMargin=16*mm, bottomMargin=16*mm,
        title=f"AI-Agent Internal Knowledge Analysis - {analysis.organization.name}",
        author="AI-Agent",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AIATitle", parent=styles["Title"], alignment=TA_CENTER,
        fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=colors.HexColor("#1F4E79"),
        spaceAfter=5*mm,
    )
    org_style = ParagraphStyle(
        "AIAOrg", parent=styles["Heading2"], alignment=TA_CENTER,
        fontName="Helvetica-Bold", fontSize=11, textColor=colors.HexColor("#334155"),
        spaceAfter=5*mm,
    )
    h1 = ParagraphStyle(
        "AIAH1", parent=styles["Heading1"], fontName="Helvetica-Bold",
        fontSize=12, leading=15, textColor=colors.HexColor("#1F4E79"),
        spaceBefore=5*mm, spaceAfter=2.5*mm,
    )
    body = ParagraphStyle(
        "AIABody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9.3, leading=13, spaceAfter=2.5*mm,
    )
    note = ParagraphStyle(
        "AIANote", parent=body, fontName="Helvetica-BoldOblique",
        textColor=colors.HexColor("#1F4E79"), backColor=colors.HexColor("#EFF6FF"),
        borderPadding=6, spaceAfter=3*mm,
    )

    story = [
        Paragraph("AI-AGENT INTERNAL KNOWLEDGE ANALYSIS", title_style),
        Paragraph(safe(analysis.organization.name), org_style),
    ]

    meta = [
        [Paragraph("<b>Knowledge Status</b>", body), Paragraph(safe(analysis.validation_status), body)],
        [Paragraph("<b>Origin</b>", body), Paragraph("Customer-specific Internal Analysis", body)],
        [Paragraph("<b>Created</b>", body), Paragraph(safe(analysis.created_at.strftime("%d/%m/%Y %H:%M") if analysis.created_at else ""), body)],
    ]
    meta_table = Table(meta, colWidths=[48*mm, 120*mm])
    meta_table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#CBD5E1")),
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#D9EAF7")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story += [meta_table, Spacer(1, 3*mm)]

    story += [Paragraph("1. Question / Objective", h1), Paragraph(safe(sections.get("QUESTION") or analysis.title), body)]

    sentences = [x.strip() for x in customer_text.replace("\n", " " ).split(". " ) if x.strip()]
    summary = ". ".join(sentences[:3])
    if summary and not summary.endswith("."):
        summary += "."
    story += [Paragraph("2. Executive Summary", h1), Paragraph(safe(summary or "Customer evidence analysis is available below."), body)]

    story.append(Paragraph("3. Customer / Internal Information", h1))
    paragraphs = [x.strip() for x in customer_text.split("\n") if x.strip()] or [customer_text]
    for p in paragraphs:
        story.append(Paragraph(safe(p), body))

    story.append(Paragraph("4. Gaps / Information Requiring Confirmation", h1))
    if gaps:
        data = [[Paragraph("<b>Area</b>", body), Paragraph("<b>Status</b>", body), Paragraph("<b>Information Required</b>", body)]]
        statuses = []
        for line in [x for x in gaps.splitlines() if x.strip()]:
            parts = [x.strip() for x in line.split("|", 2)]
            while len(parts) < 3:
                parts.append("")
            statuses.append(parts[1])
            data.append([Paragraph(safe(parts[0]), body), Paragraph(safe(parts[1]), body), Paragraph(safe(parts[2]), body)])
        table = Table(data, colWidths=[47*mm, 28*mm, 93*mm], repeatRows=1)
        commands = [
            ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#CBD5E1")),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1F4E79")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
            ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ]
        for idx, status in enumerate(statuses, start=1):
            if status == "PARTIAL":
                commands.append(("BACKGROUND", (1,idx), (1,idx), colors.HexColor("#FFF2CC")))
            elif status == "NOT_FOUND":
                commands.append(("BACKGROUND", (1,idx), (1,idx), colors.HexColor("#F4CCCC")))
        table.setStyle(TableStyle(commands))
        story.append(table)
    else:
        story.append(Paragraph("No unresolved information gaps were stored with this analysis.", body))

    story += [
        Paragraph("5. Recommended Approach", h1),
        Paragraph("AI-Agent recommendation - not customer-provided information.", note),
    ]
    for line in [x.strip() for x in recommendation.splitlines() if x.strip()] or ["No recommendation was generated."]:
        story.append(Paragraph(safe(line), body))

    story.append(Paragraph("6. Evidence / Sources", h1))
    sources = list(analysis.evidence_sources.filter(is_active=True).order_by("name"))
    if sources:
        for source in sources:
            story.append(Paragraph("• " + safe(source.name), body))
    else:
        story.append(Paragraph("No evidence-source links are attached to this analysis record.", body))

    story += [
        Paragraph("7. Knowledge Validation", h1),
        Paragraph(
            "This document reflects the AI-Agent analysis record and its current validation status. "
            "Customer facts are derived from linked Internal Knowledge evidence; recommendations are AI-Agent guidance.",
            body,
        ),
    ]

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawCentredString(A4[0] / 2, 8*mm, f"Generated by AI-Agent | Internal Working Document | Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    filename = get_valid_filename(f"AI-Agent_{analysis.organization.name}_{analysis.id}.pdf")
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def export_generic_analysis_docx(request, analysis_id):
    """Export an attachment-grounded Generic Knowledge analysis to Word."""
    if not user_has_ai_access(request.user):
        return HttpResponse("Access denied.", status=403)

    try:
        analysis = AnalysisKnowledge.objects.prefetch_related("evidence_sources").get(
            id=analysis_id, organization__isnull=True, is_active=True
        )
    except AnalysisKnowledge.DoesNotExist:
        return HttpResponse("Generic analysis report not found.", status=404)

    try:
        from io import BytesIO
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Inches, Pt, RGBColor
    except ImportError:
        return HttpResponse("Word export requires python-docx.", status=500)

    def parse_sections(content):
        headings = {
            "QUESTION", "EXECUTIVE SUMMARY", "KEY FINDINGS",
            "DETAILED ANALYSIS", "SOURCES / EVIDENCE"
        }
        data, current = {}, None
        for line in (content or "").splitlines():
            s = line.strip()
            if s in headings:
                current = s
                data.setdefault(current, [])
            elif current:
                data[current].append(line)
        return {k: "\n".join(v).strip() for k, v in data.items()}

    sections = parse_sections(analysis.content)
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Inches(0.65)
    sec.bottom_margin = Inches(0.65)
    sec.left_margin = Inches(0.7)
    sec.right_margin = Inches(0.7)
    doc.styles["Normal"].font.name = "Aptos"
    doc.styles["Normal"].font.size = Pt(10)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("AI-AGENT GENERIC KNOWLEDGE ANALYSIS")
    r.bold = True
    r.font.size = Pt(18)
    r.font.color.rgb = RGBColor(31, 78, 121)

    doc.add_heading("1. Question", level=1)
    doc.add_paragraph(sections.get("QUESTION", ""))

    doc.add_heading("2. Executive Summary", level=1)
    doc.add_paragraph(sections.get("EXECUTIVE SUMMARY", "No executive summary was generated."))

    doc.add_heading("3. Key Findings", level=1)
    findings = sections.get("KEY FINDINGS", "")
    for line in [x.strip().lstrip("-• ").strip() for x in findings.splitlines() if x.strip()]:
        doc.add_paragraph(line, style="List Bullet")

    doc.add_heading("4. Detailed Analysis", level=1)
    for line in [x.strip() for x in sections.get("DETAILED ANALYSIS", "").splitlines() if x.strip()]:
        doc.add_paragraph(line)

    doc.add_heading("5. Evidence / Sources", level=1)
    sources = list(analysis.evidence_sources.filter(is_active=True).order_by("name"))
    if sources:
        for source in sources:
            doc.add_paragraph(source.name, style="List Bullet")
    else:
        doc.add_paragraph("No attachment evidence is linked to this report.")

    doc.add_heading("6. Knowledge Trace", level=1)
    doc.add_paragraph("Report type: Generic Knowledge attachment analysis")
    doc.add_paragraph("Validation status: " + analysis.validation_status)
    doc.add_paragraph("Attached documents are evidence for this request and are not automatically promoted to trusted Generic Knowledge.")

    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("Generated by AI-Agent | Generic Knowledge Analysis").font.size = Pt(8)

    buffer = BytesIO()
    doc.save(buffer)
    filename = get_valid_filename(f"AI-Agent_Generic_Analysis_{analysis.id}.docx")
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def export_generic_analysis_pdf(request, analysis_id):
    """Export an attachment-grounded Generic Knowledge analysis to PDF."""
    if not user_has_ai_access(request.user):
        return HttpResponse("Access denied.", status=403)

    try:
        analysis = AnalysisKnowledge.objects.prefetch_related("evidence_sources").get(
            id=analysis_id, organization__isnull=True, is_active=True
        )
    except AnalysisKnowledge.DoesNotExist:
        return HttpResponse("Generic analysis report not found.", status=404)

    try:
        import html as html_lib
        from io import BytesIO
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    except ImportError:
        return HttpResponse("PDF export requires reportlab.", status=500)

    def parse_sections(content):
        headings = {
            "QUESTION", "EXECUTIVE SUMMARY", "KEY FINDINGS",
            "DETAILED ANALYSIS", "SOURCES / EVIDENCE"
        }
        data, current = {}, None
        for line in (content or "").splitlines():
            s = line.strip()
            if s in headings:
                current = s
                data.setdefault(current, [])
            elif current:
                data[current].append(line)
        return {k: "\n".join(v).strip() for k, v in data.items()}

    def safe(value):
        return html_lib.escape(str(value or "")).replace("\n", "<br/>")

    sections = parse_sections(analysis.content)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=16*mm, leftMargin=16*mm, topMargin=16*mm, bottomMargin=16*mm,
        title="AI-Agent Generic Knowledge Analysis", author="AI-Agent",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "GenericTitle", parent=styles["Title"], alignment=TA_CENTER,
        fontName="Helvetica-Bold", fontSize=17, leading=21,
        textColor=colors.HexColor("#1F4E79"), spaceAfter=5*mm,
    )
    h1 = ParagraphStyle(
        "GenericH1", parent=styles["Heading1"],
        fontName="Helvetica-Bold", fontSize=12,
        textColor=colors.HexColor("#1F4E79"), spaceBefore=4*mm, spaceAfter=2*mm,
    )
    body = ParagraphStyle(
        "GenericBody", parent=styles["BodyText"],
        fontName="Helvetica", fontSize=9.5, leading=14, spaceAfter=2.5*mm,
    )

    story = [Paragraph("AI-AGENT GENERIC KNOWLEDGE ANALYSIS", title_style)]
    for heading, key in [
        ("1. Question", "QUESTION"),
        ("2. Executive Summary", "EXECUTIVE SUMMARY"),
        ("3. Key Findings", "KEY FINDINGS"),
        ("4. Detailed Analysis", "DETAILED ANALYSIS"),
    ]:
        story.append(Paragraph(heading, h1))
        value = sections.get(key, "") or "No information was generated."
        for line in [x.strip() for x in value.splitlines() if x.strip()]:
            prefix = "• " if key == "KEY FINDINGS" else ""
            story.append(Paragraph(prefix + safe(line.lstrip("-• ").strip()), body))

    story.append(Paragraph("5. Evidence / Sources", h1))
    sources = list(analysis.evidence_sources.filter(is_active=True).order_by("name"))
    if sources:
        for source in sources:
            story.append(Paragraph("• " + safe(source.name), body))
    else:
        story.append(Paragraph("No attachment evidence is linked to this report.", body))

    story.append(Paragraph("6. Knowledge Trace", h1))
    story.append(Paragraph(
        safe(
            "Report type: Generic Knowledge attachment analysis\n"
            f"Validation status: {analysis.validation_status}\n"
            "Attached documents are request evidence and are not automatically promoted to trusted Generic Knowledge."
        ), body
    ))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawCentredString(
            A4[0] / 2, 8*mm,
            f"Generated by AI-Agent | Generic Knowledge Analysis | Page {document.page}"
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    filename = get_valid_filename(f"AI-Agent_Generic_Analysis_{analysis.id}.pdf")
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def generic_knowledge_progress(request):
    """
    Stream real Generic Knowledge processing stages as NDJSON.

    Progress is emitted by the actual service workflow. No global progress
    variable is used; each request has its own in-memory queue.
    """
    if request.method != "POST":
        return StreamingHttpResponse(
            iter([json.dumps({"type": "error", "message": "POST required."}) + "\n"]),
            content_type="application/x-ndjson",
            status=405,
        )

    question = (request.POST.get("question") or "").strip()
    ai_provider = (request.POST.get("ai_provider") or "openai").strip().lower()
    if ai_provider not in {"openai", "copilot"}:
        ai_provider = "openai"

    attached_files = request.FILES.getlist("generic_attachments")

    if not question:
        return StreamingHttpResponse(
            iter([json.dumps({"type": "error", "message": "Question is required."}) + "\n"]),
            content_type="application/x-ndjson",
            status=400,
        )

    if ai_provider == "copilot":
        return StreamingHttpResponse(
            iter([json.dumps({
                "type": "error",
                "message": (
                    "Microsoft Copilot is selected, but the Copilot Studio connection is "
                    "pending administrator activation. OpenAI was not used."
                ),
                "ai_provider": "MICROSOFT_COPILOT",
                "openai_used": False,
            }) + "\n"]),
            content_type="application/x-ndjson",
            status=503,
        )

    event_queue = queue.Queue()
    request_user = request.user if request.user.is_authenticated else None
    attachment_summary = {
        "received": len(attached_files),
        "ingested": 0,
        "chunks_stored": 0,
        "files": [],
        "failures": [],
    }

    # Generic attachments are ingested locally as organization-neutral knowledge
    # sources. They enter the existing KnowledgeSource/KnowledgeChunk/TermCandidate
    # pipeline and are NOT automatically promoted to trusted GenericKnowledge.
    if attached_files:
        upload_root = Path(settings.BASE_DIR) / "Knowledge_Inbox" / "Generic_Knowledge"
        upload_root.mkdir(parents=True, exist_ok=True)
        storage = FileSystemStorage(location=str(upload_root))

        for uploaded_file in attached_files:
            safe_name = get_valid_filename(Path(uploaded_file.name).name)
            if not safe_name:
                attachment_summary["failures"].append({
                    "name": uploaded_file.name or "Unnamed file",
                    "error": "Invalid filename.",
                })
                continue

            stored_name = None
            try:
                stored_name = storage.save(safe_name, uploaded_file)
                stored_path = upload_root / stored_name
                ingest_result = ingest_file(
                    file_path=stored_path,
                    source_name=Path(safe_name).stem,
                    organization=None,
                    created_by=request_user,
                )
                stored_chunks = int(ingest_result.get("stored_chunks", 0) or 0)
                attachment_summary["ingested"] += 1
                attachment_summary["chunks_stored"] += stored_chunks
                attachment_summary["files"].append({
                    "name": safe_name,
                    "source_id": ingest_result.get("source_id"),
                    "stored_chunks": stored_chunks,
                    "candidate_terms": int(ingest_result.get("candidate_terms", 0) or 0),
                })
            except Exception as exc:
                if stored_name and storage.exists(stored_name):
                    storage.delete(stored_name)
                attachment_summary["failures"].append({
                    "name": safe_name,
                    "error": str(exc),
                })

    def progress_callback(percent, stage):
        event_queue.put({
            "type": "progress",
            "percent": int(percent),
            "stage": stage,
        })

    def worker():
        close_old_connections()
        try:
            if attachment_summary["received"]:
                progress_callback(
                    10,
                    f'Attachments processed locally: {attachment_summary["ingested"]}/'
                    f'{attachment_summary["received"]} file(s), '
                    f'{attachment_summary["chunks_stored"]} content record(s) stored'
                )

            if attachment_summary["ingested"]:
                progress_callback(30, "Reading attached-file evidence from local database")
                attachment_source_ids = [
                    item["source_id"] for item in attachment_summary["files"]
                    if item.get("source_id")
                ]
                evidence_chunks = list(
                    KnowledgeChunk.objects.filter(
                        source_id__in=attachment_source_ids,
                        source__is_active=True,
                    ).select_related("source").order_by("source_id", "chunk_index")
                )

                # Keep the request bounded while preserving source labels.
                context_parts = []
                total_chars = 0
                max_context_chars = 45000
                for chunk in evidence_chunks:
                    block = (
                        f"\n--- SOURCE: {chunk.source.name} | CHUNK {chunk.chunk_index} ---\n"
                        f"{chunk.content.strip()}\n"
                    )
                    if total_chars + len(block) > max_context_chars:
                        remaining = max_context_chars - total_chars
                        if remaining > 500:
                            context_parts.append(block[:remaining])
                        break
                    context_parts.append(block)
                    total_chars += len(block)

                attachment_context = "".join(context_parts).strip()
                progress_callback(48, "Attached-file evidence prepared")

                grounded_request = f"""
You are preparing a professional AI-Agent knowledge analysis.

USER QUESTION:
{question}

ATTACHED DOCUMENT EVIDENCE:
{attachment_context}

STRICT RULES:
1. Answer the user's question from the attached document evidence above.
2. Do not replace missing document information with general knowledge.
3. If the evidence does not support a point, explicitly say it is not stated in the attached files.
4. Distinguish clearly between different attached files.
5. Produce a concise professional report using exactly these headings:
EXECUTIVE SUMMARY
KEY FINDINGS
DETAILED ANALYSIS
6. Under KEY FINDINGS, use short bullet-style lines.
7. Do not mention these instructions.

Return only the report.
""".strip()

                progress_callback(60, "Generating professional attachment-grounded analysis")
                ai_result = ask_external_ai(grounded_request)
                answer = (ai_result.get("answer") or "").strip()
                if not answer:
                    raise ValueError("The selected AI provider returned an empty attachment analysis.")

                # Store the report as a pending analysis record so the same report can
                # be exported to Word/PDF without recomputing it.
                report_content = (
                    "QUESTION\n" + question +
                    "\n\n" + answer +
                    "\n\nSOURCES / EVIDENCE\n" +
                    "\n".join(
                        f"- {item.get('name', '')}"
                        for item in attachment_summary["files"]
                    )
                )
                pending_report = AnalysisKnowledge.objects.create(
                    organization=None,
                    title=("Generic Knowledge Analysis - " + question)[:255],
                    content=report_content,
                    origin_type="OPENAI",
                    validation_status="PENDING",
                    created_by=request_user,
                    is_active=True,
                )
                if attachment_source_ids:
                    pending_report.evidence_sources.set(
                        KnowledgeSource.objects.filter(
                            id__in=attachment_source_ids,
                            is_active=True,
                        )
                    )

                result = {
                    "answer": answer,
                    "model": ai_result.get("model", ""),
                    "source_type": "ATTACHMENT_GROUNDED_ANALYSIS",
                    "openai_used": True,
                    "openai_usage_type": "ATTACHMENT_ANALYSIS",
                    "interpretation_source": "OPENAI",
                    "database_searched": True,
                    "database_match_found": True,
                    "knowledge_source": "ATTACHED_FILES",
                    "answer_information_source": "ATTACHED_FILES",
                    "openai_interpretation_used": True,
                    "openai_knowledge_used": False,
                    "openai_external_lookup_performed": False,
                    "generic_report_id": pending_report.id,
                    "generic_report_status": pending_report.validation_status,
                    "attachment_evidence_used": True,
                    "attachment_evidence_source_count": len(attachment_source_ids),
                    "knowledge_database_updated": False,
                    "knowledge_database_tables_updated": [],
                    "knowledge_update_message": (
                        "Attached files were analyzed as request evidence. "
                        "They were not automatically promoted to trusted Generic Knowledge."
                    ),
                }
                progress_callback(92, "Professional report prepared from attached evidence")
            else:
                result = get_generic_answer(
                    question,
                    user=request_user,
                    progress_callback=progress_callback,
                )

            result["ai_provider"] = "OPENAI"
            result["attached_files_count"] = attachment_summary["received"]
            result["attached_files_ingested"] = attachment_summary["ingested"]
            result["attachment_chunks_stored"] = attachment_summary["chunks_stored"]
            result["attachment_files"] = attachment_summary["files"]
            result["attachment_failures"] = attachment_summary["failures"]
            result["attachments_openai_used"] = bool(
                attachment_summary["ingested"] and result.get("openai_used")
            )
            result["attachments_promoted_to_generic_knowledge"] = False
            event_queue.put({
                "type": "result",
                "result": result,
            })
        except Exception as exc:
            event_queue.put({
                "type": "error",
                "message": str(exc),
            })
        finally:
            close_old_connections()
            event_queue.put({"type": "done"})

    def event_stream():
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        while True:
            event = event_queue.get()
            yield json.dumps(event, default=str) + "\n"
            if event.get("type") == "done":
                break

    response = StreamingHttpResponse(
        event_stream(),
        content_type="application/x-ndjson",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
def external_ai_progress(request):
    """
    Stream an explicit OpenAI API / External Knowledge request as NDJSON.

    This endpoint is separate from Generic Knowledge. It does not search
    Generic Knowledge and does not automatically store the external answer.
    """
    if not user_has_ai_access(request.user):
        return StreamingHttpResponse(
            iter([json.dumps({"type": "error", "message": "Access denied."}) + "\n"]),
            content_type="application/x-ndjson",
            status=403,
        )

    if request.method != "POST":
        return StreamingHttpResponse(
            iter([json.dumps({"type": "error", "message": "POST required."}) + "\n"]),
            content_type="application/x-ndjson",
            status=405,
        )

    provider = (request.POST.get("provider") or "").strip().lower()
    symbol = (request.POST.get("symbol") or "").strip().upper()

    if provider == "alpaca":
        question = symbol
    else:
        question = (request.POST.get("question") or "").strip()

    if not question:
        return StreamingHttpResponse(
            iter([json.dumps({"type": "error", "message": "Question is required."}) + "\n"]),
            content_type="application/x-ndjson",
            status=400,
        )

    event_queue = queue.Queue()

    def emit(percent, stage):
        event_queue.put({
            "type": "progress",
            "percent": int(percent),
            "stage": stage,
        })

    def worker():
        close_old_connections()
        try:
            if provider == "alpaca":
                emit(5, "API request received")
                emit(25, "Connected application selected: Alpaca Market Data")
                emit(50, f"Requesting latest trade for {symbol}")
                result = get_alpaca_latest_trade(symbol)
                emit(72, "Latest Alpaca trade received")
                try:
                    chart_bars = get_alpaca_recent_bars(symbol, limit=36)
                except Exception:
                    chart_bars = []
                emit(90, "Live Alpaca market data received")

                price = result.get("price")
                currency = result.get("currency", "USD")
                timestamp = result.get("timestamp") or "N/A"
                feed = (result.get("feed") or "").upper()

                payload = {
                    "answer": (
                        f"Latest available trade for {result.get('symbol', symbol)}: "
                        f"{price} {currency}\n"
                        f"Timestamp: {timestamp}\n"
                        f"Market data feed: {feed}"
                    ),
                    "model": "",
                    "source_type": "LIVE_API",
                    "openai_used": False,
                    "openai_usage_type": "NONE",
                    "interpretation_source": "DIRECT_API_REQUEST",
                    "database_searched": False,
                    "database_match_found": False,
                    "knowledge_source": "ALPACA_API",
                    "answer_information_source": "ALPACA_MARKET_DATA",
                    "openai_interpretation_used": False,
                    "openai_knowledge_used": False,
                    "openai_external_lookup_performed": False,
                    "automatically_stored": False,
                    "live_api_used": True,
                    "provider": "ALPACA",
                    "symbol": result.get("symbol", symbol),
                    "price": price,
                    "currency": currency,
                    "timestamp": timestamp,
                    "feed": result.get("feed", ""),
                    "bars": chart_bars,
                }

                emit(100, "Connected API request completed")
                event_queue.put({"type": "result", "result": payload})
            else:
                emit(5, "Question received")
                emit(20, "Explicit OpenAI API mode confirmed")
                emit(35, "Preparing external knowledge request")
                emit(50, "Requesting external knowledge from OpenAI")

                result = ask_external_ai(question)

                emit(90, "External OpenAI response received")

                payload = {
                    "answer": result.get("answer", ""),
                    "model": result.get("model", ""),
                    "source_type": result.get("source_type", "OPENAI_EXTERNAL"),
                    "openai_used": True,
                    "openai_usage_type": "EXPLICIT_EXTERNAL_KNOWLEDGE",
                    "interpretation_source": "OPENAI",
                    "database_searched": False,
                    "database_match_found": False,
                    "knowledge_source": "OPENAI_EXTERNAL",
                    "answer_information_source": "OPENAI",
                    "openai_interpretation_used": False,
                    "openai_knowledge_used": True,
                    "openai_external_lookup_performed": True,
                    "automatically_stored": False,
                }

                emit(100, "External OpenAI request completed")
                event_queue.put({"type": "result", "result": payload})
        except Exception as exc:
            event_queue.put({
                "type": "error",
                "message": str(exc),
            })
        finally:
            close_old_connections()
            event_queue.put({"type": "done"})

    def event_stream():
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        while True:
            event = event_queue.get()
            yield json.dumps(event, default=str) + "\n"
            if event.get("type") == "done":
                break

    response = StreamingHttpResponse(
        event_stream(),
        content_type="application/x-ndjson",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
def generic_knowledge_candidates(request):
    """
    Review staged Generic Knowledge candidates.

    POST is intentionally SAFE: it analyzes/consolidates the pending pool for
    human review. It does NOT promote candidates into final Generic Knowledge.
    """
    if not user_has_ai_access(request.user):
        return render(request, 'ai_agent/access_denied.html', status=403)

    if not user_is_ai_admin(request.user):
        return render(request, 'ai_agent/access_denied.html', status=403)

    processing_available = True

    if request.method == "POST":
        action = (request.POST.get("action") or "analyze").strip().lower()

        try:
            if action in {"gate2_keep_separate", "gate2_approve_merge", "gate2_reject"}:
                candidate_id = (request.POST.get("candidate_id") or "").strip()
                candidate = GenericKnowledgeCandidate.objects.filter(
                    pk=candidate_id,
                    status="PENDING",
                ).first()
                if candidate is None:
                    raise ValueError("The selected Pending candidate was not found.")

                gate2_review = (candidate.analysis_json or {}).get("gate2_review") or {}
                if not gate2_review.get("review_required"):
                    raise ValueError(
                        "This candidate is not currently waiting for Gate 2 human review."
                    )

                if action == "gate2_reject":
                    with transaction.atomic():
                        locked = GenericKnowledgeCandidate.objects.select_for_update().get(
                            pk=candidate.id
                        )
                        audit = dict(locked.analysis_json or {})
                        review = dict(audit.get("gate2_review") or {})
                        review["human_decision"] = "REJECT"
                        review["human_decided_at"] = timezone.now().isoformat()
                        review["human_decided_by"] = request.user.username
                        audit["gate2_review"] = review

                        locked.status = "REJECTED"
                        locked.error_message = ""
                        locked.processed_at = timezone.now()
                        locked.analysis_json = audit
                        locked.save(update_fields=[
                            "status", "error_message", "processed_at",
                            "analysis_json", "updated_at",
                        ])
                    messages.success(
                        request,
                        f"Candidate #{candidate.id} rejected by human review. "
                        "No Generic Knowledge was changed."
                    )

                elif action == "gate2_approve_merge":
                    result = promote_generic_knowledge_candidate(
                        candidate.id,
                        human_override="APPROVE_MERGE",
                    )
                    refreshed = GenericKnowledgeCandidate.objects.get(pk=candidate.id)
                    audit = dict(refreshed.analysis_json or {})
                    review = dict(audit.get("gate2_review") or {})
                    review["human_decision"] = "APPROVE_MERGE"
                    review["human_decided_at"] = timezone.now().isoformat()
                    review["human_decided_by"] = request.user.username
                    review["human_result_status"] = result.get("status")
                    review["human_result_generic_knowledge_id"] = result.get(
                        "generic_knowledge_id"
                    )
                    review["human_result_items_created"] = result.get("items_created", 0)
                    audit["gate2_review"] = review
                    GenericKnowledgeCandidate.objects.filter(pk=candidate.id).update(
                        analysis_json=audit
                    )
                    messages.success(
                        request,
                        f"Candidate #{candidate.id} approved and merged into Generic Knowledge "
                        f"#{result.get('generic_knowledge_id')}."
                    )

                else:
                    result = promote_generic_knowledge_candidate(
                        candidate.id,
                        human_override="KEEP_SEPARATE",
                    )
                    refreshed = GenericKnowledgeCandidate.objects.get(pk=candidate.id)
                    audit = dict(refreshed.analysis_json or {})
                    review = dict(audit.get("gate2_review") or {})
                    review["human_decision"] = "KEEP_SEPARATE"
                    review["human_decided_at"] = timezone.now().isoformat()
                    review["human_decided_by"] = request.user.username
                    review["human_result_status"] = result.get("status")
                    review["human_result_generic_knowledge_id"] = result.get(
                        "generic_knowledge_id"
                    )
                    audit["gate2_review"] = review
                    GenericKnowledgeCandidate.objects.filter(pk=candidate.id).update(
                        analysis_json=audit
                    )
                    messages.success(
                        request,
                        f"Candidate #{candidate.id} approved as separate Generic Knowledge "
                        f"#{result.get('generic_knowledge_id')}."
                    )

            elif action == "apply":
                result = apply_pending_generic_knowledge_consolidation()
                messages.success(request, result["message"])

            elif action == "gate2":
                gate2_candidates = list(
                    GenericKnowledgeCandidate.objects
                    .filter(status="PENDING")
                    .order_by("created_at", "id")
                )

                eligible = []
                blocked = []

                for candidate in gate2_candidates:
                    consolidation = (
                        (candidate.analysis_json or {})
                        .get("pending_consolidation") or {}
                    )
                    database_action = consolidation.get("database_action")

                    if database_action == "CANONICAL_RETAINED_PENDING_FOR_GATE_2":
                        eligible.append(candidate)
                    else:
                        blocked.append(candidate.id)

                if blocked:
                    raise ValueError(
                        "Gate 2 stopped safely. These PENDING candidates have not "
                        f"completed Gate 1B Apply Consolidation: {blocked}."
                    )

                if not eligible:
                    messages.info(request, "No Gate 2 eligible PENDING candidates found.")
                else:
                    promoted = 0
                    reused = 0
                    review_required = 0
                    failed = 0

                    for candidate in eligible:
                        try:
                            gate2_result = promote_generic_knowledge_candidate(candidate.id)

                            # Preserve the Gate 2 decision/result in the candidate audit trail.
                            refreshed = GenericKnowledgeCandidate.objects.get(pk=candidate.id)
                            audit = dict(refreshed.analysis_json or {})
                            audit["gate2_review"] = {
                                "processed_at": timezone.now().isoformat(),
                                "status": gate2_result.get("status"),
                                "generic_knowledge_id": gate2_result.get("generic_knowledge_id"),
                                "items_created": gate2_result.get("items_created", 0),
                                "duplicate_reused": gate2_result.get("duplicate_reused", False),
                                "review_required": gate2_result.get("review_required", False),
                                "consolidation_decision": gate2_result.get("consolidation_decision"),
                                "semantic_consolidation": gate2_result.get("semantic_consolidation"),
                                "message": gate2_result.get("message"),
                            }
                            GenericKnowledgeCandidate.objects.filter(pk=candidate.id).update(
                                analysis_json=audit
                            )

                            if gate2_result.get("review_required"):
                                review_required += 1
                            elif gate2_result.get("duplicate_reused"):
                                reused += 1
                            elif gate2_result.get("status") == "COMPLETED":
                                promoted += 1
                        except Exception as exc:
                            failed += 1
                            refreshed = GenericKnowledgeCandidate.objects.filter(pk=candidate.id).first()
                            if refreshed:
                                audit = dict(refreshed.analysis_json or {})
                                audit["gate2_review"] = {
                                    "processed_at": timezone.now().isoformat(),
                                    "status": refreshed.status,
                                    "generic_knowledge_id": refreshed.promoted_generic_knowledge_id,
                                    "review_required": refreshed.status == "PENDING",
                                    "technical_error": str(exc),
                                    "message": "Gate 2 wrapper encountered a technical error after processing.",
                                }
                                GenericKnowledgeCandidate.objects.filter(pk=candidate.id).update(
                                    analysis_json=audit
                                )

                    messages.success(
                        request,
                        "Gate 2 completed. "
                        f"Newly promoted: {promoted}; "
                        f"Existing knowledge reused: {reused}; "
                        f"Returned for human review: {review_required}; "
                        f"Failed: {failed}."
                    )

            else:
                result = analyze_pending_generic_knowledge()
                messages.success(request, result["message"])

        except Exception as exc:
            if action == "apply":
                messages.error(request, f"Apply Consolidation stopped safely: {exc}")
            elif action == "gate2":
                messages.error(request, f"Gate 2 stopped safely: {exc}")
            else:
                messages.error(request, f"Pending knowledge analysis failed: {exc}")

        return redirect("generic_knowledge_candidates")

    candidates = (
        GenericKnowledgeCandidate.objects
        .select_related("promoted_generic_knowledge")
        .order_by("-created_at")
    )

    # Attach read-only display helpers from analysis_json; no DB schema change.
    for candidate in candidates:
        consolidation = (candidate.analysis_json or {}).get("pending_consolidation") or {}
        candidate.pending_ai_review = consolidation.get("review") or {}
        candidate.pending_ai_group = consolidation.get("group") or {}
        candidate.gate2_review = (candidate.analysis_json or {}).get("gate2_review") or {}
        candidate.gate2_matched_knowledge = None
        gate2_gk_id = candidate.gate2_review.get("generic_knowledge_id")
        if gate2_gk_id:
            candidate.gate2_matched_knowledge = GenericKnowledge.objects.filter(
                pk=gate2_gk_id
            ).first()

    context = {
        "candidates": candidates,
        "pending_count": candidates.filter(status="PENDING").count(),
        "processing_count": candidates.filter(status="PROCESSING").count(),
        "completed_count": candidates.filter(status="COMPLETED").count(),
        "failed_count": candidates.filter(status="FAILED").count(),
        "rejected_count": candidates.filter(status="REJECTED").count(),
        "processing_available": processing_available,
    }
    return render(request, "mentor/generic_knowledge_candidates.html", context)


@login_required
def generic_knowledge_candidates_progress(request):
    """
    Stream Gate 1B Pending Knowledge Consolidation progress as NDJSON.

    SAFE: analysis only. No promotion, rejection, deletion, merge, or final
    Generic Knowledge write occurs in this endpoint.
    """
    if not user_has_ai_access(request.user) or not user_is_ai_admin(request.user):
        return StreamingHttpResponse(
            iter([json.dumps({"type": "error", "message": "Access denied."}) + "\n"]),
            content_type="application/x-ndjson",
            status=403,
        )

    if request.method != "POST":
        return StreamingHttpResponse(
            iter([json.dumps({"type": "error", "message": "POST required."}) + "\n"]),
            content_type="application/x-ndjson",
            status=405,
        )

    event_queue = queue.Queue()

    def worker():
        close_old_connections()
        try:
            def progress(percent, stage):
                event_queue.put({
                    "type": "progress",
                    "percent": int(percent),
                    "stage": stage,
                })

            result = analyze_pending_generic_knowledge(
                progress_callback=progress,
            )
            event_queue.put({
                "type": "result",
                "result": result,
            })
        except Exception as exc:
            event_queue.put({"type": "error", "message": str(exc)})
        finally:
            close_old_connections()
            event_queue.put({"type": "done"})

    def event_stream():
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        while True:
            event = event_queue.get()
            yield json.dumps(event, default=str) + "\n"
            if event.get("type") == "done":
                break

    response = StreamingHttpResponse(
        event_stream(),
        content_type="application/x-ndjson",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
def reset_knowledge(request):
    if not user_has_ai_access(request.user):
        return render(request, 'ai_agent/access_denied.html', status=403)

    if not user_is_ai_admin(request.user):
        return render(request, 'ai_agent/access_denied.html', status=403)

    context = {'error': ''}

    if request.method == 'POST':
        confirmation = (request.POST.get('confirmation') or '').strip()

        if confirmation != 'RESET':
            context['error'] = 'Please type RESET exactly to confirm.'
        else:
            deleted = reset_knowledge_base()
            messages.success(
                request,
                'Knowledge Base reset completed successfully. '
                f"Deleted {deleted['knowledge_sources']} source(s), "
                f"{deleted['knowledge_chunks']} searchable content record(s), "
                f"{deleted['knowledge_items']} reusable knowledge item(s), "
                f"{deleted['analysis_knowledge']} analysis knowledge item(s), "
                f"and {deleted['topics']} topic(s)."
            )
            return redirect('dashboard')

    return render(request, 'ai_agent/reset_knowledge.html', context)


@csrf_exempt
def copilot_ask_api(request):
    """
    Microsoft Copilot Studio -> AI-Agent LOCAL KNOWLEDGE endpoint.

    IMPORTANT:
    - This endpoint does NOT call get_generic_answer().
    - This endpoint does NOT call OpenAI.
    - It returns only local Generic Knowledge records from PostgreSQL.
    - Copilot Studio can use the returned records as its external tool evidence.

    Authentication:
      Authorization: Bearer <COPILOT_API_KEY>

    Request JSON:
      {"question": "CCTV", "limit": 10}
    """
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required."}, status=405)

    configured_key = (os.environ.get("COPILOT_API_KEY") or "").strip()
    auth_header = (request.headers.get("Authorization") or "").strip()

    if not configured_key:
        return JsonResponse(
            {"ok": False, "error": "Copilot API is not configured on the server."},
            status=503,
        )

    if not secrets.compare_digest(auth_header, f"Bearer {configured_key}"):
        return JsonResponse({"ok": False, "error": "Unauthorized."}, status=401)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"ok": False, "error": "Request body must be valid JSON."},
            status=400,
        )

    question = str(payload.get("question") or "").strip()
    if not question:
        return JsonResponse({"ok": False, "error": "Question is required."}, status=400)

    try:
        limit = int(payload.get("limit") or 10)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 25))

    # Deliberately simple and auditable local retrieval for the first Copilot POC.
    # No embeddings, no external AI, and no OpenAI interpretation are invoked here.
    terms = [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.+-]*", question)
        if len(token) >= 2
    ]
    terms = list(dict.fromkeys(terms))

    queryset = GenericKnowledgeItem.objects.filter(
        is_active=True,
        generic_knowledge__is_active=True,
    ).select_related("generic_knowledge")

    if terms:
        match_filter = models.Q()
        for term in terms:
            match_filter |= models.Q(description__icontains=term)
            match_filter |= models.Q(concept__icontains=term) | models.Q(knowledge_aspect__icontains=term) | models.Q(generic_knowledge__title__icontains=term) | models.Q(generic_knowledge__question__icontains=term) | models.Q(generic_knowledge__content__icontains=term)
        queryset = queryset.filter(match_filter)
    else:
        queryset = queryset.none()

    matches = []
    for item in queryset.order_by("generic_knowledge_id", "id")[:limit]:
        knowledge = item.generic_knowledge
        matches.append({
            "generic_knowledge_id": knowledge.id,
            "generic_knowledge_item_id": item.id,
            "concept": item.concept or "",
            "knowledge_aspect": item.knowledge_aspect or "",
            "title": knowledge.title or "",
            "description": item.description or "",
            "generic_knowledge_content": knowledge.content or "",
            "original_source_type": knowledge.source_type or "",
            "original_model_name": knowledge.model_name or "",
            "source": "AI_AGENT_LOCAL_DATABASE",
        })

    return JsonResponse({
        "ok": True,
        "question": question,
        "found": bool(matches),
        "matches": matches,
        "match_count": len(matches),

        # Explicit provenance / audit fields.
        "request_channel": "MICROSOFT_COPILOT_STUDIO",
        "retrieval_provider": "AI_AGENT_DJANGO",
        "knowledge_provider": "AI_AGENT_LOCAL_DATABASE",
        "database_searched": True,
        "openai_api_used": False,
        "external_ai_used": False,
        "answer_generated_by_django": False,
        "trace_note": (
            "This endpoint returned local database evidence only. "
            "No direct OpenAI API call was made by Django."
        ),
    })


def logout_view(request):
    logout(request)
    return redirect('login')
