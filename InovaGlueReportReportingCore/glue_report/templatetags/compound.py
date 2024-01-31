from django import template
from django.conf import settings
# Models
from inova_core.models import Compuesta
# Helpers
from inova_base.helpers.question.entity_type import get_entity_question_value
# Constants
from inova_core.constants.question import question_type
import requests
from django.template.loader import get_template

register = template.Library()


@register.simple_tag(takes_context=True)
def get_compound(context, question, responses, allresponses, entyty_rule):
    compound_question = Compuesta.objects.using(settings.REPORTING_CORE_DB).filter(pregunta__pk=question['pk'])
    sub_questions = compound_question.first().subpreguntas.filter(
        versiones__contains=[context['object'].norma.version]
    ).order_by('orden', 'pk')
    results = get_result_questions(allresponses)
    total_context = {
        'sub_questions': sub_questions,
        'results': results,
        'responses': responses,
        'question': question,
        'compound': compound_question[0],
        'tipo': context['tipo'],
        'allresponses': allresponses,
        'entity_rule': entyty_rule,
        'idiom': context['idiom']
    }
    html_template = get_template('compound_table.html').render(total_context)
    return html_template


@register.simple_tag()
def get_value(header_pk, items):
    lista = list(filter(lambda x: x['subpregunta']['pk'] == header_pk, items))
    return lista[0]['valor'] if lista else ''


@register.simple_tag()
def get_result_item(header_pk, items):
    for item in items:
        if 'subpregunta' in item['pregunta'] and header_pk == item['pregunta']['subpregunta']:
            return item['respuesta_tipo']['valor']
    return


@register.simple_tag()
def get_question_entity(primary_key, question, response, info_client_rule):
    if isinstance(question, list):
        response = 0
        for question_item in question:
            if question_item['subpregunta']['pk'] == primary_key:
                response = question_item['valor']
    text = get_entity_question_value(primary_key, response, using=settings.REPORTING_CORE_DB)
    return text


def get_result_questions(allresponses):
    return list(
        filter(lambda i: i['pregunta']['tipo'] == question_type.RESULT, allresponses)
    )
