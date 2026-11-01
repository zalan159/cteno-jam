"""python -m cteno_jam.review_cli <song-id>  — (re)run the AI review on an analysed song."""
import logging
import sys

from . import config, review_job, store


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = config.get()
    st = store.Store(cfg.songs_dir)
    res = review_job.review(st, argv[0], cfg)
    return 0 if res.get("ok") else 3


if __name__ == "__main__":
    sys.exit(main())
