"""Two explicit missing-model probes supplement an auth-less local gateway matrix.

Default prints a plan. Does not claim a gateway enforces authentication when it
accepts arbitrary keys. Never repeats scientific tasks or imports real secrets.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
import uuid

if 'silicolab_acceptance' in sys.modules:a=sys.modules['silicolab_acceptance']
else:
    spec=importlib.util.spec_from_file_location('silicolab_acceptance',Path(__file__).with_name('verify.py'))
    a=importlib.util.module_from_spec(spec);sys.modules['silicolab_acceptance']=a;spec.loader.exec_module(a)

MISSING_MODEL='silicolab-acceptance-no-such-model-8c074a9b'
REQUIRED=('savedPaused','sameReceiver','requestError','boundedAttempts','noTool','safeError')
CORE_NAMES={name for name in a.CASE_CHECKS if not name.startswith('invalid-key-')}


def bounded_attempts(requests):
    return 1<=len(requests)<=3 and [r.get('attempt') for r in requests]==list(range(1,len(requests)+1)) and all(r.get('status')=='error' for r in requests)


def error_passed(case):
    checks=case.get('checks',{})
    return set(checks)==set(REQUIRED) and all(checks[key] is True for key in REQUIRED)


def core_passed(report):
    original=report.get('cases',[])
    if (len(original)!=8 or {c.get('case') for c in original}!=set(a.CASE_CHECKS) or
        any(not isinstance(c.get('taskId'),str) or not c['taskId'] for c in original) or len({c['taskId'] for c in original})!=8):return False
    cases=[c for c in original if c.get('case') in CORE_NAMES]
    return len(cases)==6 and {c['case'] for c in cases}==CORE_NAMES and all(a.case_passed(c) for c in cases)


def compatibility_passed(report,errors):
    cases=errors.get('cases',[])
    return (report.get('evidenceKind')=='real' and errors.get('evidenceKind')=='real' and core_passed(report) and
            errors.get('sourceReportSha256')==a.sha256(a.canonical(report)) and len(cases)==2 and {c.get('protocol') for c in cases}==set(a.PROTOCOLS) and
            all(error_passed(c) for c in cases))


def build_plan(report,*,resume_error=None):
    if not core_passed(report):raise ValueError('两类科学、双向切换与取消六项必须已有完整通过证据')
    configs=report['plan']['configurations']
    current=a.build_plan([{**c,'hasKey':True} for c in configs],[c['id'] for c in configs],evidence_kind=report['evidenceKind'],allow_local_gateway=report['plan'].get('allowLocalGateway',False))
    if report['plan'].get('applicationSourceSha256')!=current['applicationSourceSha256']:raise ValueError('应用源码改变，不能沿用旧矩阵')
    plan={'format':'silicolab-missing-model-probes-v1','configurations':configs,'evidenceKind':report['evidenceKind'],
          'sourceReportSha256':a.sha256(a.canonical(report)),'applicationSourceSha256':current['applicationSourceSha256'],
          'runnerSha256':a.sha256(Path(__file__).read_bytes()),'sharedVerifierSha256':a.sha256(Path(__file__).with_name('verify.py').read_bytes()),
          'modelId':MISSING_MODEL,'maximumTasks':2,'taskTimeoutSeconds':90,
          'scope':'仅向已选两个协议端点各发送一次不存在模型ID的人工请求；固定无效key，不读取真实key；最多既有3次瞬态尝试，失败不重跑。正常应在路由层拒绝，但不保证网关不产生上游请求。'}
    if resume_error is not None:
        cases=resume_error.get('cases',[])
        if (resume_error.get('sourceReportSha256')!=plan['sourceReportSha256'] or resume_error.get('evidenceKind')!=report['evidenceKind'] or
            len(cases)!=1 or cases[0].get('protocol')!='openai-responses' or not error_passed(cases[0]) or not bounded_attempts(cases[0].get('requests',[]))):raise ValueError('只能复用已核验的首项错误记录')
        plan['resumeErrorSha256']=a.sha256(a.canonical(resume_error));plan['maximumTasks']=1
        plan['scope']='只执行尚未执行的Messages不存在模型检查；已核验Responses错误不重发。'+plan['scope']
    plan['digest']=a.sha256(a.canonical(plan));return plan


def run(application,source,plan,workspace,approved_digest,*,resume_error=None):
    if approved_digest!=plan['digest'] or build_plan(source,resume_error=resume_error)!=plan:raise ValueError('不存在模型检查计划未获匹配授权')
    configs=application.request('/model-configs')
    for expected in plan['configurations']:
        if not any(all(c.get(k)==v for k,v in expected.items()) for c in configs):raise ValueError('所选端点或配置已变更')
    projects=application.request('/projects')
    if len(projects)!=1:raise ValueError('只允许原专用人工项目')
    url='/projects/'+projects[0]['id'];state=application.request(url)
    prefix=resume_error['cases'] if resume_error else []
    if [t['id'] for t in state['tasks']]!=[c['taskId'] for c in source['cases']+prefix]:raise ValueError('原任务清单已变更，不重新发送')
    if prefix:
        task=state['tasks'][-1];case=prefix[0];expected=source['plan']['configurations'][0]
        observed=a.request_evidence(task,{'id':'unused','protocol':'unused','baseUrl':'unused','modelId':'unused'})
        if task['status']!='paused' or task['toolExecutions'] or observed['requests']!=case['requests'] or observed['executionContract']!=case.get('executionContract'):raise ValueError('原错误任务证据变更')
        if not all(r['endpoint']==expected['baseUrl'] and r['protocol']==expected['protocol'] and r['model']==MISSING_MODEL for r in observed['requests']):raise ValueError('原错误接收方不符')
        snapshot=application.request(url+'/conversations/'+task['conversationId'])
        if any(secret in a.canonical(snapshot).decode() for secret in (a.INVALID_KEY,a.ERROR_RESPONSE_MARKER)):raise ValueError('原错误包含敏感回显')
    for task,case in zip(state['tasks'],source['cases']):
        observed=a.request_evidence(task,{'id':'unused','protocol':'unused','baseUrl':'unused','modelId':'unused'})
        if task['status']!=case['status'] or observed['requests']!=case['requests'] or observed['executionContract']!=case.get('executionContract'):raise ValueError('原任务证据改变')
        if case['case'].startswith(('science-','switch-')):
            conversation=application.request(url+'/conversations/'+task['conversationId'])
            own={'entries':[e for e in conversation['entries'] if str(e['id']).startswith(task['id']+'-')]}
            if not a.references_result(a.assistant_text(own)):raise ValueError('已有实际结果引用无法重新核对')
            if case['case'].startswith('science-'):
                executions=task.get('toolExecutions',[])
                artifacts=[{k:item[k] for k in ('name','sha256','size') if k in item} for item in executions[0].get('artifacts',[])] if len(executions)==1 else []
                if not artifacts or artifacts!=case.get('artifacts'):raise ValueError('原报告产物与当前manifest不符，未提交补充任务')
                if not a.verify_artifacts(application,url,task):raise ValueError('已有科学产物无法重新核对')
            if case['case'].startswith('switch-') and task['toolExecutions']:raise ValueError('已有切换重跑了科学工具')
    workspace=Path(workspace);workspace.mkdir(parents=True,exist_ok=False)
    report={'plan':plan,'evidenceKind':source['evidenceKind'],'sourceReportSha256':plan['sourceReportSha256'],'versions':a.versions(),'startedAt':a.now(),'cases':json.loads(json.dumps(prefix)),
            'authentication401403':'unverified: selected local gateway accepts arbitrary keys','realCompatibilityPassed':False}
    active=None;pending=None;temporary=None;configuration_intent=None;observer=None
    def save():(workspace/'error-probe-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    save()
    try:
        for config in plan['configurations'][len(prefix):]:
            configuration_intent={'name':'人工不存在模型检查 '+uuid.uuid4().hex,'protocol':config['protocol'],'baseUrl':config['baseUrl'],'modelId':MISSING_MODEL}
            report['pendingConfiguration']=dict(configuration_intent);save()
            temporary=application.request('/model-configs',{**configuration_intent,'apiKey':a.INVALID_KEY})
            configuration_intent=None;report.pop('pendingConfiguration',None);save()
            chat=application.request(url+'/conversations',{'title':'人工不存在模型 '+config['protocol']})['id']
            application.request(url+'/conversations/'+chat+'/model',{'configurationId':temporary['id']},'PUT')
            pending={'conversationId':chat,'requestId':str(uuid.uuid4())};report['pendingSubmission']=pending;save()
            task=application.request(url+'/tasks',{**pending,'goal':'人工不存在模型验证。不要调用工具，只答OK。','authorizedTools':['synthetic_count'],'acceptanceModel':{k:temporary[k] for k in ('id','protocol','baseUrl','modelId')}})
            active=task['id'];pending=None;report.pop('pendingSubmission',None);save()
            observer=a.StreamObservation(application,url+'/conversations/'+chat,active,sensitive=(a.INVALID_KEY,a.ERROR_RESPONSE_MARKER))
            deadline=time.monotonic()+plan['taskTimeoutSeconds']
            while time.monotonic()<deadline:
                snapshot=application.request(url+'/conversations/'+chat);task=next(t for t in snapshot['tasks'] if t['id']==active)
                if task['status'] in a.TERMINAL:break
                time.sleep(.05)
            else:raise TimeoutError('不存在模型检查超过时间限制')
            observer.close();stream=observer.snapshot();observer=None
            evidence=a.request_evidence(task,temporary)
            checks={'savedPaused':task['status']=='paused','sameReceiver':evidence['sameReceiver'],
                    'requestError':bool(evidence['requests']) and all(r['status']=='error' for r in evidence['requests']),
                    'boundedAttempts':bounded_attempts(evidence['requests']),'noTool':task['toolExecutions']==[],
                    'safeError':not stream['sensitiveContentObserved'] and not any(secret in a.canonical(snapshot).decode() for secret in (a.INVALID_KEY,a.ERROR_RESPONSE_MARKER))}
            report['cases'].append({**evidence,'protocol':config['protocol'],'checks':checks});active=None;save()
            application.request('/model-configs/'+temporary['id'],method='DELETE');temporary=None
            if not all(checks.values()):raise ValueError('实际错误检查未通过，停止后续请求')
        report['realCompatibilityPassed']=compatibility_passed(source,report)
    except (Exception,KeyboardInterrupt) as error:
        report['failureType']=type(error).__name__
        if pending and active is None:
            try:
                matches=[t for t in application.request(url)['tasks'] if all(t.get(k)==v for k,v in pending.items())]
                if len(matches)==1:active=matches[0]['id']
                else:report['submissionOutcomeUnconfirmed']=True
            except Exception:report['submissionOutcomeUnconfirmed']=True
        if active:
            try:application.request(url+'/tasks/'+active+'/cancel',{},'POST')
            except Exception:report['cancellationUnconfirmed']=True
        raise
    finally:
        if observer:observer.close()
        if configuration_intent and temporary is None:
            try:
                matches=[c for c in application.request('/model-configs') if all(c.get(k)==v for k,v in configuration_intent.items())]
                if len(matches)==1:temporary=matches[0]
                else:report['temporaryConfigurationCleanupUnconfirmed']=True
            except Exception:report['temporaryConfigurationCleanupUnconfirmed']=True
        if temporary:
            try:application.request('/model-configs/'+temporary['id'],method='DELETE')
            except Exception:report['temporaryConfigurationCleanupUnconfirmed']=True
        report['finishedAt']=a.now();save()
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--app-directory',type=Path,required=True);parser.add_argument('--source-report',type=Path,required=True)
    parser.add_argument('--workspace',type=Path);parser.add_argument('--approve-plan-sha256');parser.add_argument('--resume-error',type=Path);args=parser.parse_args()
    from silicolab.desktop_lifecycle import service_info
    info=service_info(args.app_directory)
    if not info or info.get('isolatedResources') is not True:raise ValueError('需要原隔离人工验收后台')
    source=json.loads(args.source_report.read_text());prefix=json.loads(args.resume_error.read_text()) if args.resume_error else None;plan=build_plan(source,resume_error=prefix)
    if not args.approve_plan_sha256:print(json.dumps(plan,ensure_ascii=False,indent=2));return
    if not args.workspace:raise ValueError('需要新的报告目录')
    app=a.Application(info['origin'])
    try:
        result=run(app,source,plan,args.workspace,args.approve_plan_sha256,resume_error=prefix)
        print(json.dumps({'realCompatibilityPassed':result['realCompatibilityPassed'],'authentication401403':result['authentication401403']}))
        if not result['realCompatibilityPassed']:raise SystemExit(1)
    finally:app.close()


if __name__=='__main__':main()
