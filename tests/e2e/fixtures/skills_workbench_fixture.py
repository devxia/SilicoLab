"""Temporary artificial skill trees, conflicts and incompatible file; no real user resources."""
import os
from pathlib import Path
import sys
import tempfile
import uvicorn
from fastapi import FastAPI
from silicolab.server import create_app

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'backend' / 'tests'))
from test_skill_resources import skill

if __name__ == '__main__':
    os.environ['SILICOLAB_SCIENCE_REMOTE'] = 'http://127.0.0.1:9/toDnaAjaxCodon'
    with tempfile.TemporaryDirectory(prefix='silicolab-skills-ui-') as directory:
        root = Path(directory)
        project = root / 'project'
        project.mkdir()
        user = root / 'user-skills'
        skill(user, 'artificial')
        skill(project / '.agents/skills', 'artificial', body='ARTIFICIAL_UI_PROJECT_BODY')
        broken = user / 'broken'
        broken.mkdir()
        (broken / 'SKILL.md').write_text('broken artificial file')
        def no_science(_payload):
            raise RuntimeError('No actual science in skills fixture')
        workbench = create_app(root / 'app.sqlite3', optimizer=no_science, delay=0, skill_roots=[str(user)], mcp_roots=[])
        app = FastAPI(lifespan=workbench.router.lifespan_context)
        @app.get('/__test/skill-project')
        def project_path():
            return {'path': str(project)}
        app.mount('/', workbench)
        uvicorn.run(app, host='127.0.0.1', port=8767, log_level='warning')
