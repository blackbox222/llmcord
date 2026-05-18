"""Virtual file system for static content and the memory command."""
import io
import logging
import sqlite3
from typing import Any, BinaryIO, Collection

import fs.base
import fs.errors
import fs.info
import fs.multifs
import fs.permissions
import fs.subfs
import fs.wrap


log = logging.getLogger(__name__)


class Sqlite3FS(fs.base.FS):
  conn: sqlite3.Connection

  def __init__(self, path: str):
    self.conn = sqlite3.connect(path, autocommit=True)
    self.conn.set_trace_callback(lambda s: print("sql:", s))

    cur = self.conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL")
    cur.execute("CREATE VIRTUAL TABLE IF NOT EXISTS files USING fts5(path, contents)")
    cur.execute("INSERT OR IGNORE INTO files (path, contents) VALUES ('/', '')")

  def getinfo(self, path: str, namespaces: Collection[str] | None = None) -> fs.info.Info:
    path = self.validatepath(path)
    cur = self.conn.cursor()
    cur.execute("SELECT path FROM files WHERE path IN (?, ?)", (path, path + '/'))

    row = cur.fetchone()
    if row is None:
      raise fs.errors.ResourceNotFound(path)

    stored_path = row[0]
    return fs.info.Info(dict(basic=dict(name=stored_path, is_dir=stored_path.endswith("/"))))

  def listdir(self, path: str) -> list[str]:
    path = self.validatepath(path)
    cur = self.conn.cursor()
    cur.execute("SELECT path FROM files WHERE path IN (?, ?)", (path, path + '/'))

    row = cur.fetchone()
    if row is None:
      raise fs.errors.ResourceNotFound(path)

    stored_path = row[0]
    if stored_path.endswith('/'):
      cur.execute("SELECT path FROM files WHERE path LIKE ?", (stored_path + '%',))
      if paths := cur.fetchall():
        return [p[0].removesuffix(stored_path).split('/', maxsplit=1)[0] for p in paths]
      else:
        return []

    raise fs.errors.DirectoryExpected(path)

  def makedir(self, path: str, permissions: fs.permissions.Permissions | None = None, recreate: bool = False) -> fs.subfs.SubFS:
    path = self.validatepath(path)
    if not path.endswith('/'):
      path += '/'
    cur = self.conn.cursor()
    cur.execute("INSERT INTO files (path, contents) VALUES (?, '')", (path,))

    return fs.subfs.SubFS(self, path)

  def openbin(self, path: str, mode: str = "r", buffering: int = -1, **kwargs) -> BinaryIO:
    path = self.validatepath(path)
    cur = self.conn.cursor()
    cur.execute("SELECT contents FROM files WHERE path = ?", (path,))

    row = cur.fetchone()
    if row is None:
      raise fs.errors.ResourceNotFound(path)

    return io.BytesIO(row[0].encode('utf-8', 'replace'))

  def remove(self, path: str) -> None:
    raise NotImplementedError
    path = self.validatepath(path)
    cur = self.conn.cursor()
    cur.execute("DELETE FROM files WHERE path = ? LIMIT 1", (path,))

  def removedir(self, path: str) -> None:
    raise NotImplementedError
    path = self.validatepath(path)
    if not path.endswith('/'):

      raise fs.errors.DirectoryExpected(path)
    cur = self.conn.cursor()
    cur.execute("DELETE FROM files WHERE path = ? OR path LIKE ? || '%'", (path, path))
    self.conn.commit()

  def setinfo(self, path: str, info: dict[str, dict[str, object]]) -> None:
    raise NotImplementedError
    path = self.validatepath(path)
    if 'basic' in info and 'name' in info['basic']:
      name = info['basic']['name']
      new_path = (path.rstrip('/') + '/' + str(name)) if info['basic'].get('is_dir') else path.rstrip('/')
      new_path = new_path.rstrip('/')
      if path != new_path:
        cur = self.conn.cursor()
        cur.execute("UPDATE files SET path = ? WHERE path = ?", (new_path, path))
        self.conn.commit()
    if 'details' in info and 'size' in info['details']:
      cur = self.conn.cursor()
      cur.execute("SELECT contents FROM files WHERE path = ?", (path,))
      row = cur.fetchone()
      if row is not None:
        contents = row[0]
        size = info['details']['size']
        if len(contents) != size:
          cur.execute("UPDATE files SET contents = ? WHERE path = ?", (contents, path))
          self.conn.commit()


def create_vfs() -> fs.base.FS:
  overlay = fs.multifs.MultiFS()
  overlay.add_fs('ro', fs.wrap.read_only(fs.open_fs('./files')))
  overlay.add_fs('rw', fs.open_fs('./files_rw', writeable=True), write=True)

  return overlay
