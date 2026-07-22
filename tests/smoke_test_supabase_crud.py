import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
PAGES = ROOT / 'pages'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PAGES))
try:
    import supabase_crud as crud
    print('module_import=OK')
    print('class_options_count=', len(crud.CLASS_OPTIONS))
    print('normalize_ra_113931591=', crud.normalize_ra('113931591'))
    print('normalize_phone_14996169954=', crud.normalize_phone('14996169954'))
    print('short_class_8B=', crud.short_class_name('8 ANO 8B INTEGRAL 9H ANUAL'))
    print('relationship_label_mae=', crud.relationship_label('mãe'))
    print('relationship_label_pai=', crud.relationship_label('pai'))
    print('normalize_relationship=', crud.normalize_relationship('responsável'))
    from app.core.config import settings
    print('SUPABASE_URL_set=', bool(settings.supabase_url))
    print('SUPABASE_KEY_set=', bool(settings.supabase_key))
    print('DEFAULT_SCHOOL_ID=', settings.default_school_id)
except Exception:
    import traceback
    traceback.print_exc()
    raise
