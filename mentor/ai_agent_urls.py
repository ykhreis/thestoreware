from django.urls import path
from . import ai_agent_views as views
urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    # Upload / customer source management
    path('upload/', views.upload_information, name='upload_information'),
    path('customers/add/', views.add_customer, name='add_customer'),
    path('knowledge/sources/', views.customer_sources, name='customer_sources'),

    # Ask AI-Agent
    path('ask/', views.ask_ai_agent, name='ask_ai_agent'),
    path('ask/internal-progress/', views.internal_knowledge_progress, name='internal_knowledge_progress'),
    path('ask/internal-analysis/review/', views.review_internal_analysis, name='review_internal_analysis'),
    path('ask/internal-analysis/<int:analysis_id>/export-docx/', views.export_internal_analysis_docx, name='export_internal_analysis_docx'),
    path('ask/internal-analysis/<int:analysis_id>/export-pdf/', views.export_internal_analysis_pdf, name='export_internal_analysis_pdf'),
    path('ask/generic-progress/', views.generic_knowledge_progress, name='generic_knowledge_progress'),
    path('ask/generic-analysis/<int:analysis_id>/export-docx/', views.export_generic_analysis_docx, name='export_generic_analysis_docx'),
    path('ask/generic-analysis/<int:analysis_id>/export-pdf/', views.export_generic_analysis_pdf, name='export_generic_analysis_pdf'),
    path('ask/external-progress/', views.external_ai_progress, name='external_ai_progress'),

    # Generic Knowledge candidate workflow
    path('knowledge/candidates/', views.generic_knowledge_candidates, name='generic_knowledge_candidates'),
    path('knowledge/candidates/progress/', views.generic_knowledge_candidates_progress, name='generic_knowledge_candidates_progress'),

    path('admin/reset-knowledge/', views.reset_knowledge, name='reset_knowledge'),
    path('logout/', views.logout_view, name='logout'),
]
