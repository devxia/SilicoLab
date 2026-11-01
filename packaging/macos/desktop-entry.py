"""Frozen GUI/service entry and a small allowlist of internal science workers."""
import logging
import sys


def entry():
    args=sys.argv[1:]
    if args[:1]==['--science-supervisor']:
        if len(args)!=2 or not args[1].isdigit() or int(args[1])<3:raise ValueError('Invalid supervisor descriptor')
        from silicolab.science_supervisor import main
        main(int(args[1]));return 0
    if args[:1]==['--science-worker']:
        if len(args)!=2 or args[1] not in ('local','remote'):raise ValueError('Invalid scientific worker')
        if args[1]=='local':
            from silicolab.science_worker import main
        else:
            from silicolab.remote_science_worker import main
        main();return 0
    from silicolab.desktop import main
    return main()


if __name__=='__main__':
    try:raise SystemExit(entry())
    except Exception as error:
        logging.exception('Desktop startup failed')
        if not any(arg.startswith('--science-') or arg=='--background-service' for arg in sys.argv[1:]):
            from silicolab.desktop import show_error
            show_error(str(error))
        raise SystemExit(1)
