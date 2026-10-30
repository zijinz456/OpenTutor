import unittest
from unittest.mock import AsyncMock,MagicMock,patch
from config import settings
from services.app_lifecycle import _maybe_seed_system_data

class BootstrapSeedTests(unittest.IsolatedAsyncioTestCase):
 async def check_seed(self,enabled):
  context=MagicMock();db=AsyncMock();context.__aenter__.return_value=db
  with patch.object(settings,"app_auto_seed_system",True),patch.object(settings,"app_auto_seed_demo",enabled),patch("database.async_session",return_value=context),patch("services.templates.demo_course.seed_demo_course",new_callable=AsyncMock) as demo:
   await _maybe_seed_system_data()
   if enabled:demo.assert_awaited_once_with(db);db.commit.assert_awaited_once()
   else:demo.assert_not_awaited();db.commit.assert_not_awaited()
 async def test_blank_install_skips_demo_course(self):await self.check_seed(False)
 async def test_opt_in_demo_seeding_remains_available(self):await self.check_seed(True)
