import argparse
import json
from pathlib import Path
from .core.config import load_config
from .core.errors import ModelError, ReviewRequired
from .exposure.loaders import read_csv
from .exposure.validation import summarise_issues
from .services.analysis import analyse
from .hazard.raster import RasterHazard
from .hazard.hotspots import load_hotspots
from .services.data_audit import audit_data
from .services.sensitivity import assumption_sensitivity

def main():
    parser=argparse.ArgumentParser(description='Nairobi flood CAT backend')
    commands=parser.add_subparsers(dest='command',required=True)
    run=commands.add_parser('analyse');run.add_argument('csv');run.add_argument('--output',default='runtime/report.json')
    run.add_argument('--config');run.add_argument('--rasters');run.add_argument('--allow-partial',action='store_true')
    run.add_argument('--hotspots',help='Tag each property with its nearest named hotspot')
    serve=commands.add_parser('serve');serve.add_argument('--port',type=int,default=8000)
    audit=commands.add_parser('audit-data');audit.add_argument('directory',nargs='?',default='data');audit.add_argument('--output')
    sensitivity=commands.add_parser('sensitivity');sensitivity.add_argument('csv');sensitivity.add_argument('--output',default='runtime/sensitivity.json')
    sensitivity.add_argument('--rasters')
    imported=commands.add_parser('import-data');imported.add_argument('--exposure',default='data/exposure_nairobi_with_hazard.csv');imported.add_argument('--hotspots',default='data/nairobi_hotspots_geocoded.csv')
    admin=commands.add_parser('create-platform-admin',help='Create the first Xpat staff account');admin.add_argument('email');admin.add_argument('--name',default='Xpat staff')
    org=commands.add_parser('create-org',help='Create an organisation and e-mail its first owner an invitation');org.add_argument('name');org.add_argument('owner_email')
    org.add_argument('--seats',type=int,default=10);org.add_argument('--plan',default='pilot');org.add_argument('--domains',default='',help='Comma-separated allowed e-mail domains')
    sat=commands.add_parser('satellite-check',help='Score the hazard maps against a Sentinel-1 flood map (scripts/gee_sentinel1_flood.js)')
    sat.add_argument('flood_tif');sat.add_argument('--rasters',default='data');sat.add_argument('--hotspots',default='data/nairobi_hotspots_geocoded.csv')
    sat.add_argument('--output',default='runtime/satellite_check.json');sat.add_argument('--config')
    drain=commands.add_parser('drainage-check',help='Named-hotspot hit rate with the drainage model (prior weights; no evidence)')
    drain.add_argument('--layers',default='runtime/drainage/osm_layers.json');drain.add_argument('--rasters',default='data')
    drain.add_argument('--hotspots',default='data/nairobi_hotspots_geocoded.csv');drain.add_argument('--config')
    commands.add_parser('retention',help='Delete data past each organisation\'s retention period')
    commands.add_parser('verify-audit',help='Check the audit log hash chain')
    commands.add_parser('alerts',help='Raise security alerts from the audit log (run every few minutes)')
    commands.add_parser('init-db',help='Create the platform tables (development / SQLite)')
    commands.add_parser('generate-secret-key',help='Print a new FLOODCAT_SECRET_KEY')
    args=parser.parse_args()
    try:
        if args.command in ('create-platform-admin','create-org','retention','verify-audit','init-db','generate-secret-key','alerts'):
            return platform_command(args)
        if args.command=='serve':
            import uvicorn
            uvicorn.run('floodcat.api.app:create_app',factory=True,host='127.0.0.1',port=args.port)
        elif args.command=='audit-data':
            result=audit_data(args.directory)
            serialized=json.dumps(result,indent=2)+'\n'
            if args.output:
                Path(args.output).parent.mkdir(parents=True,exist_ok=True)
                Path(args.output).write_text(serialized)
            print(serialized,end='')
        elif args.command=='sensitivity':
            provider=RasterHazard(args.rasters).load() if args.rasters else None
            result=assumption_sensitivity(read_csv(args.csv),provider=provider)
            Path(args.output).parent.mkdir(parents=True,exist_ok=True)
            Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
            print(f'Saved {args.output}')
        elif args.command=='satellite-check':
            from .hazard.satellite import FloodExtent, compare
            result=compare(FloodExtent.read(args.flood_tif),RasterHazard(args.rasters).load(),load_config(args.config),load_hotspots(args.hotspots))
            Path(args.output).parent.mkdir(parents=True,exist_ok=True)
            Path(args.output).write_text(json.dumps(result,indent=2)+chr(10))
            print(f"Flooded pixels flagged: {result['hit_rate_any_pct']}% · dry pixels flagged: {result['dry_flag_rate_any_pct']}% · saved {args.output}")
        elif args.command=='drainage-check':
            from .hazard.drainage import DrainageAdjustment, DrainageLayers, hit_rate, prior_model
            config=load_config(args.config)
            result=hit_rate(load_hotspots(args.hotspots),RasterHazard(args.rasters).load(),DrainageAdjustment(DrainageLayers.load(args.layers),prior_model(config),config))
            print(f"Named hotspots flagged: {result['before_flagged']} of {result['hotspot_count']} by the map alone, "
                  f"{result['after_flagged']} with the drainage model (prior weights). Newly flagged: {', '.join(result['newly_flagged']) or 'none'}")
        elif args.command=='import-data':
            from .storage.repository import Repository
            result=Repository().import_starter_data(args.exposure,args.hotspots)
            print(json.dumps(result,indent=2))
        else:
            rows=read_csv(args.csv);config=load_config(args.config)
            hotspots=load_hotspots(args.hotspots) if args.hotspots else ()
            provider=RasterHazard(args.rasters).load() if args.rasters else None
            result=analyse(rows,config,provider,allow_partial=args.allow_partial,hotspots=hotspots)
            Path(args.output).parent.mkdir(parents=True,exist_ok=True)
            Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
            print(f"Saved {args.output}: {result['modelled_count']} properties, KES {result['modelled_tiv_kes']} modelled TIV")
    except ReviewRequired as exc:
        lines=[f"  {g['severity']}: {g['code']} ×{g['count']} — {g['example']}" for g in summarise_issues(exc.issues)]
        parser.exit(2,f'{exc}\n'+'\n'.join(lines)+'\nRe-run with --allow-partial to model the valid records only.\n')
    except (ModelError,OSError,ValueError) as exc:
        parser.exit(2,f'{getattr(exc,"code","input_error")}: {exc}\n')
def platform_command(args):
    import getpass
    from .platform import audit, data, identity
    from .platform.service import platform
    if args.command=='generate-secret-key':
        from cryptography.fernet import Fernet
        print(Fernet.generate_key().decode()); return
    plat=platform()
    if args.command=='init-db':
        from .platform.db import create_schema
        create_schema(plat.engine); print(f'Platform tables ready on {plat.engine.dialect.name}'); return
    with plat.tx() as conn:
        if args.command=='create-platform-admin':
            password=getpass.getpass('Password (12+ characters): ')
            if password!=getpass.getpass('Repeat password: '): raise ModelError('mismatch','Passwords do not match')
            identity.bootstrap_platform_admin(conn,args.email,args.name,password)
            print(f'Platform admin {args.email} created. Sign in at {identity.auth_url()}/auth/login and set up two-step verification.')
        elif args.command=='create-org':
            org_id,_=identity.create_organisation(conn,None,args.name,args.owner_email,plan=args.plan,seats=args.seats,
                                                  settings={'allowed_domains':[d.strip() for d in args.domains.split(',') if d.strip()]})
            print(f'Organisation {args.name} created ({org_id}). Invitation e-mailed to {args.owner_email}.')
        elif args.command=='retention':
            print(json.dumps(data.run_retention(conn)))
        elif args.command=='alerts':
            from .platform import alerts
            print(json.dumps(alerts.evaluate(conn)))
        elif args.command=='verify-audit':
            ok,bad=audit.verify_chain(conn)
            print('Audit chain intact' if ok else f'Audit chain BROKEN at event {bad}')
            if not ok: raise SystemExit(1)

if __name__=='__main__': main()
