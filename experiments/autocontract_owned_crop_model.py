"""Symbolic owned Normalize/CenterCrop/stack theorem under explicit axioms.

Only the new tiny region is modeled. No historical pair proof is upgraded;
this is not verification of native kernels or arbitrary Python ownership.
"""
from autocontract_baseline_catalog import digest


ASSUMPTIONS = (
    'trusted_startup_unmodified_builtin_and_consumer_source_to_model_mapping',
    'binary32_sub_half_then_div_half_same_coordinate_semantics_fixed_environment',
    'in_bounds_center_crop_reads_same_value_independent_center_coordinates_no_padding',
    'fresh_stack_copies_logical_sample_values_canonical_NCHW_without_retaining_intermediates',
    'private_builtin_transforms_do_not_export_temporaries_or_write_protected_roots_or_rng',
    'serial_no_hooks_callbacks_external_intermediate_or_gc_frame_observation',
    'sufficient_resources_no_interrupts_native_totality_on_declared_valid_domain',
)
HISTORY='finite_serial_complete_batches_fresh_nonshared_inputs_private_transforms_per_batch'
HALF='0x1.0000000000000p-1'


def _validate(context):
    if (context.get('boundary')!='owned_stack_batch_exit' or context.get('trusted_assumptions')!=list(ASSUMPTIONS)
            or context.get('history')!=HISTORY or context.get('baseline_order')!=['normalize','crop','stack']
            or context.get('entry')!={'batch_count':[1,4],'input_shape':'3xHxW','H':[2,8],'W':[2,8],
                'dtype':'float32','device':'cpu','values':[0,1],'ordinary_contiguous_zero_offset_no_grad':True,
                'fresh_nonshared_inputs':True,'immutable_ordered_labels_and_unique_ids':True}
            or context.get('crop_size')!=[2,2] or context.get('normalization')!={'mean_hex':[HALF]*3,'std_hex':[HALF]*3,'inplace':False}
            or context.get('ownership_basis')!='matched_audited_template_plus_declared_native_non_escape'
            or context.get('region_structure',{}).get('matched') is not True):
        raise ValueError('owned_model_context_not_supported')


def _value(image, coordinate):
    index,c,h,w=coordinate
    if image[0]=='input': return ['input_binary32_bits_at',index,c,h,w]
    if image[0]=='normalize': return ['binary32_div_RNE',['binary32_sub_RNE',_value(image[1],coordinate),HALF],HALF]
    if image[0]=='crop':
        return _value(image[1],(index,c,['add_int',['center_top','H_i',2],h],['add_int',['center_left','W_i',2],w]))
    raise ValueError('unsupported_symbolic_image')


def _observation(image):
    return {'definedness':'normal_complete_batch_under_totality_assumption',
        'output_value_at_arbitrary_coordinate':_value(image,('i','c','y','x')),
        'output_metadata':{'shape':['B',3,2,2],'stride':[12,4,2,1],'storage_offset':0,
                           'dtype':'float32','device':'cpu','layout':'strided','requires_grad':False},
        'input_post_state':'all_original_bits_metadata_and_root_aliases_unchanged',
        'labels':'same_ordered_immutable_labels','sample_ids':'same_ordered_unique_ids',
        'tensor_alias_relations':'batch_fresh_disjoint_from_inputs_and_previous_live_batches',
        'external_object_state':'owner_unchanged_private_transforms_not_exported',
        'rng_post_state':{'python':'P','numpy':'N','torch_cpu':'R'},
        'delivery_trace':'one_complete_batch_in_same_sample_order_no_partial_delivery'}


def derive(context):
    _validate(context)
    a=['crop',['normalize',['input']]]
    b=['normalize',['crop',['input']]]
    left,right=_observation(a),_observation(b)
    if left!=right: raise ValueError('owned_transition_not_equal')
    # Exhaust all supported integer dimensions, not input pixels or RNG seeds.
    offsets=[{'dimension':n,'offset':int(round((n-2)/2))} for n in range(2,9)]
    if not all(0<=x['offset']<=x['dimension']-2 for x in offsets):
        raise ValueError('center_coordinates_out_of_bounds')
    return {'proof_kind':'owned_batch_symbolic_equality_under_declared_primitive_axioms',
        'context_sha256':digest(context),'coordinate_domain':{'B':'1..4','i':'0<=i<B','c':'0<=c<3','y':'0<=y<2','x':'0<=x<2'},
        'baseline':{'image_expression':a,'batch_observation':left},
        'swapped':{'image_expression':b,'batch_observation':right},
        'center_offset_bounds':offsets,
        'totality':{'crop_in_bounds_without_padding':True,'all_sample_outputs_same_3x2x2_shape':True,
                    'sub_range':['-1/2','1/2'],'div_range':['-1','1'],'exact_nonzero_std':HALF},
        'history_induction':{'base':'equal_declared_initial_state','step':'equal_delivery_and_unchanged_protected_state',
                             'freshness':'private_transforms_recreated_and_stack_fresh_per_batch','scope':HISTORY},
        'trusted_assumptions':list(ASSUMPTIONS),'native_formally_verified':False,'execution_authorized':False}


def verify(context, certificate):
    try:
        if digest(certificate)!=digest(derive(context)):
            return {'verified':False,'reason':'owned_certificate_does_not_replay','execution_authorized':False}
        return {'verified':True,'reason':'owned_model_conditional_relation_verified',
                'native_formally_verified':False,'execution_authorized':False}
    except (ValueError,TypeError,KeyError) as exc:
        return {'verified':False,'reason':str(exc),'execution_authorized':False}
