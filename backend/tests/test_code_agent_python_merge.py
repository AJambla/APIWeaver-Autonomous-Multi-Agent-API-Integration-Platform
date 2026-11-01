import ast
from app.workflows.agents.code_agent import _merge_python_code


def test_merge_python_code_preserves_earlier_phase_methods():
    phase1_code = """
class SwaggerPetstoreClient:
    async def createUsersWithListInput(self, body=None):
        return await self._request("POST", "/user/createWithList", json=body)

    async def createUser(self, body=None):
        return await self._request("POST", "/user", json=body)

Client = SwaggerPetstoreClient
"""

    phase2_code = """
class SwaggerPetstoreClient:
    async def addPet(self, body=None):
        return await self._request("POST", "/pet", json=body)
"""

    phase4_code = """
class Client:
    async def get_inventory(self):
        return await self._request("GET", "/store/inventory")

    async def place_order(self, order_data=None):
        return await self._request("POST", "/store/order", json=order_data)
"""

    # Merge Phase 2 into Phase 1
    merged_1_2 = _merge_python_code(phase1_code, phase2_code, "client.py")
    tree = ast.parse(merged_1_2)
    cls_node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SwaggerPetstoreClient")
    methods = {m.name for m in cls_node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "createUsersWithListInput" in methods
    assert "createUser" in methods
    assert "addPet" in methods

    # Merge Phase 4 (with class Client) into Merged 1+2
    merged_all = _merge_python_code(merged_1_2, phase4_code, "client.py")
    tree_all = ast.parse(merged_all)
    cls_all = next(n for n in tree_all.body if isinstance(n, ast.ClassDef) and n.name == "SwaggerPetstoreClient")
    all_methods = {m.name for m in cls_all.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
    
    assert "createUsersWithListInput" in all_methods
    assert "createUser" in all_methods
    assert "addPet" in all_methods
    assert "get_inventory" in all_methods
    assert "place_order" in all_methods


def test_merge_python_code_handles_arbitrary_client_class_name():
    orig_code = """
class CustomServiceApi:
    async def fetch_users(self):
        pass
"""
    new_code = """
class Users:
    async def create_user(self):
        pass
"""
    merged = _merge_python_code(orig_code, new_code, "client.py")
    tree = ast.parse(merged)
    cls_node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "CustomServiceApi")
    methods = {m.name for m in cls_node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "fetch_users" in methods
    assert "create_user" in methods
