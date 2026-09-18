"""按需验证批量导入的事务失败契约。"""

import unittest

from demo_app.app.transactions import create_import_connection, import_then_continue


class TransactionContractTests(unittest.TestCase):
    def test_failed_import_rolls_back_partial_row(self):
        connection = create_import_connection()
        try:
            self.assertEqual(import_then_continue(connection), 0)
            self.assertFalse(connection.in_transaction)
        finally:
            connection.close()

    def test_connection_remains_usable_after_failed_import(self):
        connection = create_import_connection()
        try:
            import_then_continue(connection)
            connection.execute(
                "INSERT INTO imported_users (user_id, status) VALUES (?, ?)",
                ("user-002", "ready"),
            )
            connection.commit()
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM imported_users").fetchone()[0],
                1,
            )
        finally:
            connection.close()
