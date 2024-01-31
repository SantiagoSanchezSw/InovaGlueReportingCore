import json

import boto3
from django.conf import settings
from inova_base.helpers.boto3_helper import generate_s3_temp_url
from reporting_core.classes import AWSClient
from reporting_core.helpers import report_or_visit_changed, rename_report
from reporting_core.models import ReportGeneration, Report, CustomReport
from botocore.exceptions import WaiterError


def build_report_in_lambda(visit, client, custom_report):
    report_request = ReportGeneration.objects.create(
        visit_id=visit.pk,
        client_id=client.pk,
        custom_report=custom_report if custom_report else None,
    )
    client = instance_client()
    lambda_response = client.invoke(
        FunctionName=settings.GENERATE_REPORT_FUNCTION_NAME,
        InvocationType='RequestResponse',
        Payload=json.dumps({'pathParameters': {'id': report_request.pk}})
    )
    execution_id = lambda_response['ExecutedVersion']
    """waiter = client.get_waiter('function_exists')
    wait_for_lambda_completion(settings.GENERATE_REPORT_FUNCTION_NAME, execution_id, waiter)"""

    qs = Report.objects.filter(visit_id=visit.pk, rule_id=visit.norma.pk)
    if custom_report is not None:
        custom_report_qs = get_custom_report(custom_report, client, visit)
        custom_report = custom_report_qs.first() if custom_report_qs and custom_report_qs.exists() else None
        if custom_report and not report_or_visit_changed(qs, visit, custom_report):
            report_url = rename_report(qs.first().url, client, visit, custom_report)
            return generate_s3_temp_url(report_url)
    return generate_s3_temp_url(qs.first().url)


def get_custom_report(custom_report, client, visit):
    if custom_report is not None:
        custom_report = CustomReport.objects.filter(pk=custom_report.pk)
    else:
        custom_report_qs = CustomReport.objects.filter(client_id=client.pk, rule_id=visit.norma_id, default=True)
        custom_report = custom_report_qs if custom_report_qs.exists() else None
    return custom_report


def instance_client():
    return boto3.client(
        'lambda',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )


def wait_for_lambda_completion(function_name, execution_id, waiter):
    try:
        waiter.wait(
            FunctionName=function_name,
            Qualifier=execution_id,
            WaiterConfig={'Delay': 4, 'MaxAttempts': 30}
        )
    except WaiterError as e:
        raise Exception(f'Error esperando la finalización de la ejecución de Lambda: {e}')
