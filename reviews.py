"""Private, incremental implementation reviews; no model calls or public uploads."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

PROJECT_FILE = '.engineering-workflow-project.json'
SECTIONS = ('outcome', 'purpose_decisions', 'evidence_limits', 'standards_implications', 'your_attention')
PLATFORMS = ('claude', 'codex', 'gemini')
SECRETS = re.compile(r'(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}'
    r'|AKIA[0-9A-Z]{16}|xox[abprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----'
    r'|(?i:password|api[_ -]?key|secret)\s*[:=]\s*[^\s,;]+)')
CONTACT = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+|(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)')


def load(path): return json.loads(Path(path).read_text())
def encode(value): return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
def sha(value): return hashlib.sha256(encode(value)).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()


def git(root, *args):
    run = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=15)
    return run.stdout.strip() if not run.returncode else None


def project_root(path):
    path = Path(path).resolve()
    return Path(git(path, 'rev-parse', '--show-toplevel') or path).resolve()


def safe_path(root, *parts):
    root = Path(root).resolve()
    path = root.joinpath(*parts)
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('Review path escapes its storage root')
    return path


def private_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.review-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream: stream.write(encode(value))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def immutable_write(path, value):
    if path.exists():
        if load(path) != value: raise ValueError('Immutable review history conflict; no revision was overwritten')
        return
    private_write(path, value)


def state_root(args):
    default = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'engineering-workflow'
    path = Path(args.state_dir or default).expanduser().resolve()
    if path.is_relative_to(project_root(args.project)):
        raise ValueError('Private review state must be outside the project checkout')
    return path


@contextmanager
def locked(root):
    root.mkdir(parents=True, exist_ok=True)
    fd = os.open(safe_path(root, '.review.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def identifier(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Expected a canonical UUID')
    return value


def text(value, label, empty=False):
    if not isinstance(value, str) or len(value) > 24_000 or ('\x00' in value) or (not empty and not value.strip()):
        raise ValueError('Invalid ' + label)
    return value.strip()


def slug(value):
    value = re.sub('[^a-z0-9]+', '-', value.lower()).strip('-')
    if not value: raise ValueError('Project needs a nonempty slug')
    return value


def clean(value):
    if isinstance(value, str): return CONTACT.sub('[REDACTED]', SECRETS.sub('[REDACTED]', value))
    if isinstance(value, list): return [clean(v) for v in value]
    if isinstance(value, dict): return {k: clean(v) for k, v in value.items()}
    return value


def refs(value):
    if not isinstance(value, dict) or set(value) - {'implementation', 'sessions'}:
        raise ValueError('Invalid evidence references')
    result = {'implementation': [], 'sessions': []}
    if any(not isinstance(value.get(key, []), list) for key in result):
        raise ValueError('Evidence reference collections must be lists')
    for item in value.get('implementation', []): result['implementation'].append(text(item, 'implementation reference'))
    for item in value.get('sessions', []):
        if not isinstance(item, dict) or set(item) != {'platform', 'id'} or item['platform'] not in PLATFORMS:
            raise ValueError('Invalid platform-qualified session reference')
        result['sessions'].append({'platform': item['platform'], 'id': text(item['id'], 'session id')})
    return clean(result)


def location(state, config, implementation):
    return safe_path(state, 'reviews', identifier(config['project_id']), identifier(implementation))


def lookup(config, key):
    item = config['implementations'].get(key)
    if not item: raise ValueError('No implementation with this key; use review upsert first')
    return identifier(item['id'])


def resolve_current(state, config, implementation, bundle=None):
    local = location(state, config, implementation) / 'review.json'
    if local.is_file(): return bound_record(load(local), config, implementation)
    if bundle:
        remote = safe_path(bundle, 'reviews', config['project_id'], implementation, 'review.json')
        if remote.is_file(): return bound_record(load(remote), config, implementation)
    raise FileNotFoundError('Review unavailable locally; configure the existing private bundle to resume')


def bundle_root(args):
    default = Path.home() / 'Projects/Open Thoughts/daydream'
    path = Path(args.bundle or os.environ.get('DAYDREAMER_BUNDLE', default)).expanduser().resolve()
    return path


def validate_record(record):
    if record.get('schema_version') != 1: raise ValueError('Unsupported review schema')
    for key in ('project_id', 'implementation_id'): identifier(record[key])
    if type(record.get('revision')) is not int or record['revision'] < 1: raise ValueError('Invalid review revision')
    if record.get('status') not in ('checkpoint', 'complete'): raise ValueError('Invalid review status')
    if record.get('public_facing') is not None and type(record['public_facing']) is not bool:
        raise ValueError('Invalid public-facing status')
    if set(record.get('sections', {})) != set(SECTIONS): raise ValueError('All five human review sections are required')
    for key in SECTIONS: text(record['sections'][key], 'review section ' + key)
    if record.get('authored_by', {}).get('platform') not in PLATFORMS: raise ValueError('Invalid review platform')
    if record['authored_by'].get('kind') != 'agent': raise ValueError('Invalid review attribution')
    text(record['title'], 'review title'); refs(record['references'])
    if slug(record['project_slug']) != record['project_slug']: raise ValueError('Invalid project slug')
    return record


def bound_record(record, config, implementation):
    validate_record(record)
    if (record['project_id'], record['implementation_id'], record['project_slug']) != (
            config['project_id'], implementation, config['project_slug']):
        raise ValueError('Review identity differs from its project/implementation locator')
    return record


def revision_record(state, config, implementation, revision, bundle):
    current = resolve_current(state, config, implementation, bundle)
    if current['revision'] == revision: return current
    for parent in (location(state, config, implementation),
                   safe_path(bundle, 'reviews', config['project_id'], implementation)):
        path = safe_path(parent, 'revisions', str(revision) + '.json')
        if path.is_file():
            record = bound_record(load(path), config, implementation)
            if record['revision'] == revision: return record
    raise ValueError('The referenced immutable review revision is unavailable')


def upsert(args):
    if args.base_revision is None or args.base_revision < 0:
        raise ValueError('Specify --base-revision (0 for the initial review)')
    draft = load(args.file)
    if not isinstance(draft, dict) or set(draft) - {'title', 'status', 'sections', 'references'}:
        raise ValueError('Review input contains unsupported fields')
    state = state_root(args)
    with locked(state):
        config = read_project(args.project)
        key = text(args.implementation, 'implementation key')
        implementation = config['implementations'].get(key, {}).get('id') or str(uuid.uuid4())
        parent = location(state, config, implementation)
        try:
            current = resolve_current(state, config, implementation, bundle_root(args))
        except FileNotFoundError:
            current = None
        actual = current['revision'] if current else 0
        if args.base_revision != actual: raise ValueError('Review revision conflict; read current revision before updating')
        timestamp = now()
        record = clean({'schema_version': 1, 'project_id': config['project_id'], 'implementation_id': implementation,
            'implementation_key': key, 'project_slug': config['project_slug'], 'title': draft.get('title'),
            'revision': actual + 1, 'status': draft.get('status'),
            'authored_by': {'kind': 'agent', 'platform': args.platform},
            'created_at': current['created_at'] if current else timestamp, 'updated_at': timestamp,
            'sections': draft.get('sections'), 'references': refs(draft.get('references', {})),
            'standard': {**config['standard'], 'section_keys': config['standard_section_keys']} if config.get('standard') else None,
            'public_facing': config['public_facing']})
        validate_record(record)
        revision_path = safe_path(parent, 'revisions', str(actual + 1) + '.json')
        if revision_path.exists():
            orphan = bound_record(load(revision_path), config, implementation)
            comparable = lambda value: {k: v for k, v in value.items() if k not in ('created_at', 'updated_at')}
            if comparable(orphan) != comparable(record):
                raise ValueError('Interrupted revision conflicts with this draft; immutable history was preserved')
            record = orphan
        # Save durable history first; metadata reservation survives an interrupted first write.
        config['implementations'][key] = {'id': implementation}
        private_write(safe_path(project_root(args.project), PROJECT_FILE), config)
        if current:
            validate_record(current)
            immutable_write(safe_path(parent, 'revisions', str(actual) + '.json'), current)
        immutable_write(revision_path, record)
        private_write(safe_path(parent, 'review.json'), record)
    return record


def show(args):
    config = read_project(args.project)
    return validate_record(resolve_current(state_root(args), config, lookup(config, args.implementation), bundle_root(args)))


def feedback(args):
    data = load(args.file)
    allowed = {'id', 'text', 'attribution', 'classification', 'standard_proposal', 'review_revision'}
    if not isinstance(data, dict) or set(data) - allowed: raise ValueError('Invalid feedback fields')
    state = state_root(args)
    with locked(state):
        config = read_project(args.project)
        implementation = lookup(config, args.implementation)
        current = validate_record(resolve_current(state, config, implementation, bundle_root(args)))
        revision = data.get('review_revision', current['revision'])
        if type(revision) is not int or revision < 1 or revision > current['revision']:
            raise ValueError('Feedback references an unavailable review revision')
        attribution = data.get('attribution')
        classification = data.get('classification', 'feedback')
        if attribution not in ('human', 'agent_interpretation') or classification not in (
                'feedback', 'local_clarification', 'shared_standard_proposal'):
            raise ValueError('Feedback requires explicit attribution and classification')
        event_id = identifier(data['id']) if data.get('id') else str(uuid.uuid4())
        result = {'schema_version': 1, 'id': event_id, 'project_id': config['project_id'],
            'implementation_id': implementation, 'review_revision': revision, 'at': now(),
            'text': text(data.get('text'), 'feedback'), 'attribution': attribution, 'classification': classification}
        if classification == 'shared_standard_proposal':
            proposed = data.get('standard_proposal', {})
            required = {'standard_key', 'standard_version', 'proposed_wording', 'evidence', 'rationale', 'expected_effect'}
            if not isinstance(proposed, dict) or set(proposed) != required:
                raise ValueError('Shared proposal needs its standard reference, wording, evidence, rationale and effect')
            reviewed = revision_record(state, config, implementation, revision, bundle_root(args))
            standard = reviewed.get('standard')
            if not standard or proposed['standard_version'] != standard['version']:
                raise ValueError('Proposal must reference the reviewed standard version')
            for field in required - {'evidence'}: text(proposed[field], 'standard proposal ' + field)
            if proposed['standard_key'] not in standard.get('section_keys', []):
                raise ValueError('Proposal references an unknown standard section')
            if not isinstance(proposed['evidence'], list) or not proposed['evidence']:
                raise ValueError('A shared proposal needs supporting evidence')
            for ref in proposed['evidence']: text(ref, 'proposal evidence')
            result.update(standard_proposal=proposed, adoption_status='proposed')
        elif 'standard_proposal' in data:
            raise ValueError('Shared-standard proposals require explicit classification')
        result = clean(result)
        parent = location(state, config, implementation)
        path = safe_path(parent, 'feedback', event_id + '.json')
        if path.exists():
            old = load(path)
            comparison = {**result, 'at': old['at']}
            if old != comparison: raise ValueError('Feedback ID conflict; immutable feedback cannot be overwritten')
            return old
        # A resumed clone may have only the remote base, which must travel with its feedback.
        if not (parent / 'review.json').exists():
            immutable_write(safe_path(parent, 'revisions', str(current['revision']) + '.json'), current)
            private_write(safe_path(parent, 'review.json'), current)
        private_write(path, result)
    return result


def synchronize(args):
    state = state_root(args)
    config = read_project(args.project)
    bundle = bundle_root(args)
    if not bundle.is_dir() or not (bundle / '.git').exists():
        raise ValueError('Private bundle unavailable; reviews remain in the private outbox')
    if bundle.is_relative_to(project_root(args.project)) and bundle != project_root(args.project) / 'daydream':
        raise ValueError('Use the configured private memory repository, not a product directory')
    changes = []
    with locked(state):
        # Coordinate workflow sync processes; this is local transport, never a git push.
        with locked(safe_path(bundle, 'reviews')):
            for item in config['implementations'].values():
                implementation = identifier(item['id'])
                parent = location(state, config, implementation)
                if not (parent / 'review.json').exists(): continue
                current = bound_record(load(parent / 'review.json'), config, implementation)
                remote_parent = safe_path(bundle, 'reviews', config['project_id'], implementation)
                remote_path = safe_path(remote_parent, 'review.json')
                if remote_path.exists():
                    remote = bound_record(load(remote_path), config, implementation)
                    if remote != current:
                        base_path = safe_path(parent, 'revisions', str(remote['revision']) + '.json')
                        if remote['revision'] >= current['revision'] or not base_path.exists() or load(base_path) != remote:
                            raise ValueError('Bundle revision conflict; neither review was overwritten')
                # Validate every planned file before writing any destination.
                for path in sorted(parent.rglob('*.json')):
                    relative = path.relative_to(parent)
                    if path.is_symlink(): raise ValueError('Review outbox contains a symlink')
                    target = safe_path(remote_parent, *relative.parts)
                    value = load(path)
                    if target.exists() and load(target) != value and relative.name != 'review.json':
                        raise ValueError('Bundle history or feedback conflict; neither version was overwritten')
                    if not target.exists() or load(target) != value: changes.append((target, value))
            for target, value in changes: private_write(target, value)
    return {'status': 'synced', 'files_written': len(changes),
        'transport': 'local private bundle; existing Daydreamer git transport publishes separately',
        'publication_approved': False}


def read_project(project):
    path = safe_path(project_root(project), PROJECT_FILE)
    if not path.is_file(): raise ValueError('Configure this project first')
    result = load(path)
    identifier(result['project_id'])
    if result.get('schema_version') != 1: raise ValueError('Unsupported project schema')
    return result


def get_standard(path):
    path = Path(path).expanduser().resolve()
    data = load(path)
    keys = [s['key'] for s in data['sections']]
    if len(keys) != 8 or len(set(keys)) != 8 or any(not re.fullmatch('[a-z][a-z0-9_]*', key) for key in keys):
        raise ValueError('Expected the authoritative eight-section standard')
    version = text(data['standard_version'], 'standard version')
    top = git(path.parent, 'rev-parse', '--show-toplevel')
    origin = git(Path(top), 'remote', 'get-url', 'origin') if top else None
    if origin:
        origin = re.sub(r'(https?://)[^/@]+@', r'\1', origin).split('?')[0]
    source = (origin.rstrip('/') + '/' + str(path.relative_to(top))) if origin else path.as_uri()
    pin = {'version': version, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
           'source': source, 'source_commit': git(path.parent, 'log', '-1', '--format=%H', '--', path.name)}
    return pin, keys


def discovery_status(config):
    if config['public_facing'] is not True:
        return {'status': 'not_required' if config['public_facing'] is False else 'audience_unknown', 'pending': []}
    if not config.get('standard'):
        return {'status': 'source_unavailable', 'pending': []}
    entries = config.get('standard_applications', {})
    pending = [key for key in config['standard_section_keys'] if key not in entries]
    return {'status': 'incomplete' if pending else 'addressed_not_verified', 'pending': pending}


def configure(args):
    root = project_root(args.project)
    path = safe_path(root, PROJECT_FILE)
    state = state_root(args)
    with locked(state):
        data = read_project(root) if path.exists() else {
            'schema_version': 1, 'project_id': str(uuid.uuid4()), 'project_slug': slug(args.slug or root.name),
            'audience': '', 'goals': [], 'public_facing': None, 'standard': None,
            'standard_section_keys': [], 'standard_applications': {}, 'implementations': {}}
        if args.public_facing is not None:
            data['public_facing'] = {'true': True, 'false': False, 'unknown': None}[args.public_facing]
        if args.audience is not None: data['audience'] = text(args.audience, 'audience', empty=True)
        if args.goal is not None: data['goals'] = [text(g, 'stated goal') for g in args.goal]
        if args.slug is not None and slug(args.slug) != data['project_slug']:
            raise ValueError('Project slug is stable after configuration; use an explicit identity migration')
        if args.standards_source:
            pin, keys = get_standard(args.standards_source)
            same_contract = lambda value: {k: value[k] for k in ('source', 'version', 'sha256')}
            if data.get('standard') and same_contract(data['standard']) != same_contract(pin):
                data.setdefault('standard_history', []).append({
                    'standard': data['standard'], 'applications': data['standard_applications']})
                data['standard_applications'] = {}
            data['standard'], data['standard_section_keys'] = pin, keys
        if args.discovery:
            if not data.get('standard'): raise ValueError('Resolve the authoritative standard before discovery')
            entries = load(args.discovery)
            if not isinstance(entries, dict) or set(entries) - set(data['standard_section_keys']):
                raise ValueError('Discovery keys must reference the pinned standard')
            for key, entry in entries.items():
                if not isinstance(entry, dict): raise ValueError('Invalid discovery entry')
                if entry.get('not_applicable_reason'):
                    text(entry['not_applicable_reason'], 'not-applicable reason')
                else:
                    for field in ('implications', 'evidence', 'tradeoffs'):
                        text(entry.get(field), 'discovery ' + field)
            data['standard_applications'].update(entries)
        data['discovery'] = discovery_status(data)
        private_write(path, data)
    return data


def project_summary(args):
    data = read_project(args.project)
    data['discovery'] = discovery_status(data)
    return data


def add_parser(sub):
    p = sub.add_parser('project', help='Project identity, audience and standards discovery')
    p.add_argument('action', choices=('configure', 'status'))
    p.add_argument('--project', default='.')
    p.add_argument('--state-dir')
    p.add_argument('--public-facing', choices=('true', 'false', 'unknown'))
    p.add_argument('--audience'); p.add_argument('--goal', action='append'); p.add_argument('--slug')
    p.add_argument('--standards-source'); p.add_argument('--discovery')
    r = sub.add_parser('review', help='Private implementation reviews and attributed feedback')
    r.add_argument('action', choices=('upsert', 'show', 'feedback', 'sync'))
    r.add_argument('--project', default='.'); r.add_argument('--state-dir'); r.add_argument('--bundle')
    r.add_argument('--implementation'); r.add_argument('--file'); r.add_argument('--base-revision', type=int)
    r.add_argument('--platform', choices=PLATFORMS, default='codex')


def run(args):
    if args.command == 'review':
        if args.action in ('upsert', 'feedback') and not args.file: raise ValueError('--file is required')
        if args.action != 'sync' and not args.implementation: raise ValueError('--implementation is required')
        return {'upsert': upsert, 'show': show, 'feedback': feedback, 'sync': synchronize}[args.action](args)
    return configure(args) if args.action == 'configure' else project_summary(args)
