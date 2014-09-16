import logging
import re
import json
from sets import Set

from django.contrib.auth.models import User
from django.http import HttpResponseBadRequest, HttpResponseNotFound, HttpResponse
from django.views.decorators.csrf import csrf_exempt
import jsonpickle
from mangrove.transport.player.new_players import XFormPlayerV2

from datawinners.dcs_app.auth import basicauth_allow_cors, response_json_cors, enable_cors
from datawinners.blue.view import SurveyWebXformQuestionnaireRequest, logger
from datawinners.blue.xform_bridge import XFormTransformer, XFormSubmissionProcessor
from datawinners.blue.xform_web_submission_handler import XFormWebSubmissionHandler
from datawinners.dcs_app.Submission import SubmissionQueryMobile
from datawinners.main.database import get_database_manager
from datawinners.search.submission_headers import HeaderFactory
from mangrove.form_model.form_model import FormModel


logger = logging.getLogger("datawinners.xlfrom.client")

@csrf_exempt
@basicauth_allow_cors()
def get_questions(request):
    start = int(request.GET.get('start', '0'))
    length = int(request.GET.get('length', '10'))

    manager =  get_database_manager(request.user)

    project_list = []
    rows = manager.load_all_rows_in_view('all_projects', descending=True)
    for row in rows:
        questionnaire = FormModel.get(manager, row['id'])
        if questionnaire.xform:
            project_temp = dict(name=questionnaire.name, project_uuid=questionnaire.id, version=questionnaire._doc.rev)
            project_list.append(project_temp)

    return response_json_cors({"projects":project_list[start:start+length],
                               "total":len(project_list),
                               "start":start,
                               "length":length})

@csrf_exempt
@basicauth_allow_cors()
def authenticate_user(request):
    return response_json_cors({'auth':'success'})

@csrf_exempt
@basicauth_allow_cors()
def get_question(request, project_uuid):
    manager = get_database_manager(request.user)
    questionnaire = FormModel.get(manager, project_uuid)
    headers = HeaderFactory(questionnaire).create_header("mobile", False).get_header_dict()

    project_temp = dict(name=questionnaire.name,
                        project_uuid=questionnaire.id,
                        version=questionnaire._doc.rev,
                        headers=json.dumps(headers),
                        xform=re.sub(r"\n", " ", XFormTransformer(questionnaire.xform).transform()))
    return response_json_cors(project_temp)

'''
id_version_dict={"12e3ed8a10af11e4b876001c42af7554":"1-4fbac7d730599bb9f9cea0bb6511e56d", "1b71e0bc130011e49e57001c42af7554": "3-6cfb65f3deaaadda8c8b36409efbd15d"}


{"ids_not_found": [], "insync_ids": ["12e3ed8a10af11e4b876001c42af7554", "1b71e0bc130011e49e57001c42af7554"], "outdated_ids": []}
'''
@csrf_exempt
@basicauth_allow_cors()
def check_submissions_status(request, project_uuid):
    req_id_version_dict = json.loads(request.POST['id_version_dict'])
    outdated_ids = []
    insync_ids = []

    manager = get_database_manager(request.user)

    req_ids = req_id_version_dict.keys()
    rows = manager.load_all_rows_in_view("survey_response_by_survey_response_id", keys=req_ids)
    id_version_dict = {r.value['_id']:r.value['_rev'] for r in rows if not r.value['void']}

    req_ids_set = Set(req_ids)
    ids = id_version_dict.keys()
    ids_not_found = list(req_ids_set.difference(ids))
    ids_found = req_ids_set.intersection(ids)

    for id_found in ids_found:
        if req_id_version_dict[id_found] == id_version_dict[id_found]:
            insync_ids.append(id_found)
        else:
            outdated_ids.append(id_found)

    return response_json_cors({
        'both':insync_ids,
        'server-deleted':ids_not_found,
        'outdated':outdated_ids})

@csrf_exempt
@basicauth_allow_cors()
def all_submissions_or_new(request, project_uuid):
    if request.method == 'GET':
        survey_request = SurveyWebXformQuestionnaireRequest(request, project_uuid, XFormSubmissionProcessor())
        content = survey_request.get_submissions()
        return response_json_cors(content)

    elif request.method == 'POST':
        try:
            form_code = get_form_code_from_xform(request.POST['form_data']);
            response = XFormWebSubmissionHandler(request=request, form_code=form_code).\
                create_new_submission_response()
            return enable_cors(response)
        except Exception as e:
            logger.exception("Exception in submission : \n%s" % e)
            return HttpResponseBadRequest()

def get_form_code_from_xform(xform):
    return re.search('<form_code>(.+?)</form_code>', xform).group(1)

@csrf_exempt
@basicauth_allow_cors()
def submission_get_or_update(request, project_uuid, submission_uuid):
    if request.method == 'GET':
        survey_request = SurveyWebXformQuestionnaireRequest(request, project_uuid, XFormSubmissionProcessor())
        content = survey_request.get_submission(submission_uuid)
        return response_json_cors(content)
    elif request.method == 'POST':
        try:
            response = XFormWebSubmissionHandler(request=request).\
                update_submission_response(submission_uuid)
            return enable_cors(response)
        except LookupError:
            return enable_cors(HttpResponseNotFound())
        except Exception as e:
            logger.exception("Exception in submission : \n%s" % e)
            return HttpResponseBadRequest()

@csrf_exempt
@basicauth_allow_cors()
def submit_submission(request):
    try:
        response = XFormWebSubmissionHandler(request=request).\
            create_new_submission_response()
        response['Location'] = request.build_absolute_uri(request.path)
        return enable_cors(response)
    except Exception as e:
        logger.exception("Exception in submission : \n%s" % e)
        return HttpResponseBadRequest()

def get_submission_headers(request):
    user = User.objects.get(username='tester150411@gmail.com')
    # NGOUserProfile.objects.filter(user=user)
    dbm = get_database_manager(user)

    form_model = FormModel.get(dbm, request.GET.get('uuid'))

    # {"submissionDatePicker":"All Dates","datasenderFilter":"","search_text":"","dateQuestionFilters":{},"uniqueIdFilters":{}}
    headers = SubmissionQueryMobile(form_model, query_params=None).get_header_dict()

    return response_json_cors({
                'data': headers
            })

# @csrf_exempt
# @logged_in_or_basicauth()
def get_server_submissions(request):
    user = User.objects.get(username='tester150411@gmail.com')
    # NGOUserProfile.objects.filter(user=user)
    dbm = get_database_manager(user)


    form_model = FormModel.get(dbm, request.GET.get('uuid'))

    search_parameters = {}
    # 4934e8e8072d11e4ae2b001c42af7554_your_name

    start = int(request.GET.get('start', '0'))
    search_parameters.update({"start_result_number": start})
    length = int(request.GET.get('length', '10'))

    search_parameters.update({"number_of_results": length})
    search_parameters.update({"filter":'all'})

    search_parameters.update({"sort_field": "date"})
    search_parameters.update({"order": ""})
    # search_parameters.update({"headers": json.loads('["c3b9ac7c07f811e4a302001c42af7554_q2"]')})


    search_filters = json.loads('{"submissionDatePicker":"All Dates","datasenderFilter":"","search_text":"","dateQuestionFilters":{},"uniqueIdFilters":{}}')

    # {"submissionDatePicker":"All Dates","datasenderFilter":"","search_text":"","dateQuestionFilters":{},"uniqueIdFilters":{}}
    search_parameters.update({"search_filters": search_filters})
    search_text = search_filters.get("search_text", '')
    search_parameters.update({"search_text": search_text})

    submission_query = SubmissionQueryMobile(form_model, search_parameters)
    header_dict = submission_query.get_header_dict()
    query_count, search_count, submissions = submission_query.paginated_query(user, form_model.id)

    return enable_cors(HttpResponse(
        json.dumps(
            {
                'data': submissions,
                'headers': header_dict.values(),
                'total': query_count,
                'start': start,
                "search_count": search_count,
                'length': length
            }), content_type='application/json'))
# type=all
# sEcho=8 iColumns=6 sColumns= iDisplayStart=0 iDisplayLength=25 sSearch= bRegex=false sSearch_0= bRegex_0=false bSearchable_0=true
# sSearch_1= bRegex_1=false bSearchable_1=true sSearch_2= bRegex_2=false bSearchable_2=true sSearch_3= bRegex_3=false bSearchable_3=true
# sSearch_4= bRegex_4=false bSearchable_4=true sSearch_5= bRegex_5=false bSearchable_5=true iSortingCols=1 iSortCol_0=2 sSortDir_0=desc
# bSortable_0=false bSortable_1=true bSortable_2=true bSortable_3=true bSortable_4=true bSortable_5=true disable_cache=1404814386137
# search_filters={"submissionDatePicker":"All Dates","datasenderFilter":"","search_text":"ssdfsdf","dateQuestionFilters":{},"uniqueIdFilters":{}}

@csrf_exempt
@basicauth_allow_cors()
def get_projects_status(request):
    outdated_projects = []
    manager =  get_database_manager(request.user)
    client_projects = json.loads(request.POST['projects'])

    for client_project in client_projects:
        try:
            server_project = FormModel.get(manager, client_project['id'])
        except Exception as e:
            outdated_projects.append({'id': client_project['id'], 'status': 'server-deleted'})
            continue
        if server_project.revision != client_project['rev']:
            outdated_projects.append({'id': server_project.id, 'status': 'outdated'})
    return response_json_cors(outdated_projects)

@csrf_exempt
@basicauth_allow_cors()
def attachment_post(request, survey_response_id):
    player = XFormPlayerV2(get_database_manager(request.user))
    player.add_new_attachments(request.FILES, survey_response_id)
    return HttpResponse(status=201)
