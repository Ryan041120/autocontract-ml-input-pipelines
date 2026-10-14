"""Verify public conditional-model examples using only the standard library.

Never imports native frameworks, accesses datasets or grants execution.
"""
import copy
import hashlib
import json
import os
import sys
from pathlib import Path

import autocontract_normalize_hflip_model as pair
import autocontract_owned_crop_model as owned

ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def check_examples(root=ROOT):
    payload = json.loads((root/'reports/research/2026-10-14/model_examples.json').read_text(encoding='utf-8'))
    for name, expected in payload['packaged_model_source_sha256'].items():
        actual = hashlib.sha256((root/name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('packaged model source changed: '+name)
    if payload['scientific_evidence'] or payload['execution_authorized']:
        raise ValueError('public examples must remain non-executable development evidence')
    checks = 0
    for example in payload['examples']:
        checker = {'pair_exit_strict':pair, 'owned_stack_batch_exit':owned}[example['boundary']]
        context, certificate = example['context'], example['certificate']
        result = checker.verify(context, certificate)
        if not result['verified'] or result['execution_authorized']:
            raise ValueError('saved model example rejected: '+example['case_id'])
        checks += 1
        changed = copy.deepcopy(context)
        changed['boundary'] = 'unmodeled_publication_boundary'
        if checker.verify(changed, certificate)['verified']:
            raise ValueError('changed boundary was admitted')
        checks += 1
        changed = copy.deepcopy(certificate)
        changed['context_sha256'] = '0'*64
        if checker.verify(context, changed)['verified']:
            raise ValueError('changed evidence binding was admitted')
        checks += 1
        changed = copy.deepcopy(certificate)
        if example['boundary'] == 'pair_exit_strict':
            changed['branches'][0]['swapped']['observation']['rng_post_state'] = {'bad':True}
        else:
            changed['swapped']['batch_observation']['output_metadata']['stride'][0] = 999
        if checker.verify(context, changed)['verified']:
            raise ValueError('changed evidence observation was admitted')
        checks += 1
    if len(payload['examples']) != 4:
        raise ValueError('expected exactly four saved model examples')
    if 'torch' in sys.modules or 'torchvision' in sys.modules:
        raise ValueError('native framework unexpectedly imported')
    return {'examples':4, 'checks_passed':checks, 'checks_total':checks,
            'native_runtime_imported':False, 'dataset_accessed':False,
            'profiling_run':False, 'training_run':False,
            'native_formally_verified':False, 'execution_authorized':False}


if __name__ == '__main__':
    print(json.dumps(check_examples(),sort_keys=True))
