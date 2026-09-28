"""
Bazaning zaxira nusxasini olish.

    python manage.py backup_db                # backups/ ga, oxirgi 14 tasi saqlanadi
    python manage.py backup_db --media        # yuklangan rasmlar (media/) ham
    python manage.py backup_db --keep 30 --dir /mnt/backup

Cron (har kuni soat 03:00):
    0 3 * * * cd /path/to/qarzdaptar && venv/bin/python manage.py backup_db --media >> logs/backup.log 2>&1
"""
import gzip
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone


class Command(BaseCommand):
    help = "Baza (va ixtiyoriy media) zaxira nusxasini oladi va eski nusxalarni o'chiradi."

    def add_arguments(self, parser):
        parser.add_argument('--dir', default=os.environ.get('BACKUP_DIR') or str(settings.BASE_DIR / 'backups'),
                            help="Zaxira papkasi (standart: backups/ yoki BACKUP_DIR)")
        parser.add_argument('--keep', type=int, default=14, help="Nechta oxirgi nusxa saqlansin (standart: 14)")
        parser.add_argument('--media', action='store_true', help="media/ papkasini ham arxivlash")

    def handle(self, *args, **options):
        backup_dir = Path(options['dir'])
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')

        engine = settings.DATABASES['default']['ENGINE']
        if engine.endswith('sqlite3'):
            db_file = self.backup_sqlite(backup_dir / f'db-{stamp}.sqlite3.gz')
        elif engine.endswith('postgresql'):
            db_file = self.backup_postgres(backup_dir / f'db-{stamp}.sql.gz')
        else:
            raise CommandError(f"Bu baza turi qo'llab-quvvatlanmaydi: {engine}")
        self.stdout.write(self.style.SUCCESS(f"Baza: {db_file} ({db_file.stat().st_size // 1024} KB)"))

        if options['media']:
            media_file = self.backup_media(backup_dir / f'media-{stamp}.tar.gz')
            if media_file:
                self.stdout.write(self.style.SUCCESS(f"Media: {media_file}"))

        removed = self.rotate(backup_dir, options['keep'])
        if removed:
            self.stdout.write(f"Eski nusxalar o'chirildi: {removed} ta")

    def backup_sqlite(self, target):
        # SQLite "online backup": server ishlab turganda ham izchil nusxa beradi
        connection.ensure_connection()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_db = Path(tmp) / 'backup.sqlite3'
            dest = sqlite3.connect(tmp_db)
            try:
                connection.connection.backup(dest)
            finally:
                dest.close()
            with open(tmp_db, 'rb') as src, gzip.open(target, 'wb') as out:
                shutil.copyfileobj(src, out)
        return target

    def backup_postgres(self, target):
        db = settings.DATABASES['default']
        cmd = ['pg_dump', '--no-owner', '-h', db.get('HOST') or 'localhost', '-p', str(db.get('PORT') or 5432),
               '-U', db['USER'], db['NAME']]
        env = dict(os.environ, PGPASSWORD=db.get('PASSWORD') or '')
        try:
            dump = subprocess.run(cmd, env=env, check=True, capture_output=True).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise CommandError(f"pg_dump xatosi: {exc}")
        with gzip.open(target, 'wb') as out:
            out.write(dump)
        return target

    def backup_media(self, target):
        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.exists():
            self.stdout.write("media/ papkasi yo'q, o'tkazib yuborildi")
            return None
        with tarfile.open(target, 'w:gz') as tar:
            tar.add(media_root, arcname='media')
        return target

    def rotate(self, backup_dir, keep):
        removed = 0
        for prefix in ('db-', 'media-'):
            files = sorted(p for p in backup_dir.iterdir() if p.name.startswith(prefix))
            for old in files[:-keep] if keep > 0 else []:
                old.unlink()
                removed += 1
        return removed
