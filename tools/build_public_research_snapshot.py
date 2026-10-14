"""Project whitelisted saved research records into a portable public snapshot.

No dataset, oracle, telemetry, partial-state or native framework access.
Never rewrites saved original records or existing publication outputs.
"""
import copy
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
DESTINATION = ROOT/'reports/research/2026-10-14'


def read(name):
    return json.loads((ROOT/name).read_text(encoding='utf-8'))


def sha(name):
    return hashlib.sha256((ROOT/name).read_bytes()).hexdigest()


def anchor(name):
    return {'original_record':name, 'original_record_sha256':sha(name),
            'evidence_role':'saved_local_development_record_not_independent_reference'}


def build():
    paths = ('outputs/autocontract_conditional_proof_checked.json',
             'outputs/autocontract_owned_batch_development.json',
             'outputs/autocontract_consolidated_development.json',
             'outputs/autocontract_p5s_div2k_aggregate.json',
             'outputs/autocontract_proof_reuse_study.json')
    pair, owned, comparison, performance, reuse = [read(name) for name in paths]
    examples = []
    for row in pair['cases']:
        main = row['methods']['autocontract']
        if main['prediction']['status'] != 'accept':
            continue
        examples.append({'case_id':row['case_id'], 'boundary':'pair_exit_strict',
                         'context':copy.deepcopy(row['public_context']),
                         'certificate':copy.deepcopy(main['artifact']['certificate']),
                         'origin':anchor(paths[0])})
    examples.append({'case_id':'tiny_owned_normalize_center_crop_stack',
                     'boundary':'owned_stack_batch_exit', 'context':copy.deepcopy(owned['context']),
                     'certificate':copy.deepcopy(owned['certificate']), 'origin':anchor(paths[1])})
    model_sources = ('experiments/autocontract_baseline_catalog.py',
                     'experiments/autocontract_comparison_request.py',
                     'experiments/autocontract_normalize_hflip_model.py',
                     'experiments/autocontract_owned_crop_model.py')
    model_payload = {'date':'2026-10-14', 'artifact_type':'public_projection_of_saved_conditional_models',
                     'scientific_evidence':False, 'independent_reference':False,
                     'native_formally_verified':False, 'execution_authorized':False,
                     'packaged_model_source_sha256':{name:sha(name) for name in model_sources},
                     'examples':examples}
    comparison_rows = []
    for row in comparison['cases']:
        methods = {}
        for name, result in row['methods'].items():
            if result.get('prediction') is None:
                methods[name] = {'prediction_present':False, 'role':'optional_manual_input_not_provided'}
            else:
                prediction = result['prediction']
                methods[name] = {'status':prediction['status'], 'evidence':prediction['evidence'],
                                 'operator_calls':result.get('artifact',{}).get('operator_calls'),
                                 'execution_authorized':False}
        comparison_rows.append({'case_id':row['case_id'], 'context_sha256':row['context_sha256'], 'methods':methods})
    claims = {'date':'2026-10-14', 'artifact_type':'public_projection_of_saved_research_findings',
              'scientific_evidence':False, 'independent_benchmark_complete':False,
              'method_advantage_established':False, 'stable_end_to_end_benefit_established':False,
              'real_task_quality_established':False, 'full_current_Cedar_API_verified':False,
              'profiling_resumed_by_publication':False,
              'saved_model_examples':{'pair_cases':3,'owned_region_cases':1,
                                     'scope':'conditional trusted model only', 'origins':[anchor(paths[0]),anchor(paths[1])]},
              'owned_development':{'configurations':len(owned['rows']), 'checks':owned['checks'],
                                   'normalize_crop_calls':owned['normalize_crop_calls'], 'stack_calls':owned['stack_calls'],
                                   'real_RandomCrop_224_448_covered':False, 'origin':anchor(paths[1])},
              'earlier_common_context_comparison':{'rows':comparison_rows, 'origin':anchor(paths[2]),
                 'limitations':['known development cases','conditional model proofs were added later in different contexts',
                                'finite accepts are not proofs','artificial cost profile is not measured benefit']},
              'proof_reuse_audit':{'cases':[{'case_id':row['case_id'],
                   'old_certificate_verified':row['old_certificate_check']['verified'],
                   'fresh_model_verified':row['fresh_model_check']['verified'],
                   'saved_declarations_match':row['saved_binding_check']['matched'],
                   'old_derivation_calls':row['old_certificate_check']['symbolic_derivation_calls'],
                   'fresh_derivation_calls':row['fresh_model_check']['symbolic_derivation_calls']}
                  for row in reuse['cases']], 'origin':anchor(paths[4]), 'actual_adapter_rerun':False,
                  'cache_speedup_measured':False},
              'P5S_historical_benefit':{'fold_medians':performance['fold_medians'],
                   'ratio_confidence_interval':performance['bootstrap']['ratio_ci'],
                   'go':performance['go'], 'required_upper_bound_strictly_below':.95,
                   'scope':'historical pinned CPU warm-cache descriptive research; scientific_evidence=false',
                   'true_classification_quality_measured':False, 'origin':anchor(paths[3])},
              'P5T_boundary':{'allowed':'pointwise eight-point calibration description only',
                   'not_allowed':['pooled acceleration','confidence intervals','selection of new workloads','reuse of old partial performance']},
              'P5V_status':{'baseline_configuration_prepared':True,'runner_fixture_development_complete':True,
                            'direct_temperature_gate_wiring_developed':True,'native_pipeline_measurement_verified':False,
                            'profiling_run':False,'resource_preparation_deferred':True},
              'human_evaluation_policy':'manual hints and human oracle optional; automatic evidence still requires valid scope and reference checks'}
    return model_payload, claims


def main():
    outputs = (DESTINATION/'model_examples.json', DESTINATION/'claims.json')
    if any(path.exists() for path in outputs):
        raise ValueError('publication outputs already exist; never overwrite')
    model_payload, claims = build()
    if len(model_payload['examples']) != 4:
        raise ValueError('expected four saved examples')
    for path, value in zip(outputs,(model_payload,claims)):
        with path.open('x',encoding='utf-8') as handle:
            json.dump(value,handle,ensure_ascii=False,indent=2,allow_nan=False)
            handle.write('\n')
    print(json.dumps({'public_model_examples':4,'known_comparison_cases':4,'offline_reuse_cases':13,
                      'datasets_accessed':False,'native_calls':0}))


if __name__ == '__main__':
    main()
