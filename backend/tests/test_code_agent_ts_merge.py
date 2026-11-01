from app.workflows.agents.code_agent import _merge_ts_code


def test_merge_ts_code_injects_into_class_not_export():
    existing_ts = """
export class SwaggerPetstoreClient {
  constructor(config: any) {}

  async getUser(id: string): Promise<any> {
    return this.request("GET", `/user/${id}`);
  }
}

export { SwaggerPetstoreClient as Client };
"""

    new_ts = """
export class SwaggerPetstoreClient {
  async getPet(petId: string): Promise<any> {
    return this.request("GET", `/pet/${petId}`);
  }
}
"""

    merged = _merge_ts_code(existing_ts, new_ts, "client.ts")

    # The new method must be inside the class body, BEFORE the closing brace of the class
    assert "async getPet(petId: string)" in merged
    # The export statement must remain intact at the end
    assert "export { SwaggerPetstoreClient as Client };" in merged
    # Must NOT have async inside export { ... }
    lines = merged.strip().splitlines()
    assert lines[-1] == "export { SwaggerPetstoreClient as Client };"
    
    # Class body should contain both methods
    class_part = merged.split("export {")[0]
    assert "getUser(" in class_part
    assert "getPet(" in class_part


def test_merge_ts_code_deduplicates_existing_methods():
    existing_ts = """
export class Client {
  async getUser(id: string): Promise<any> {
    return 1;
  }
}
"""
    new_ts = """
export class Client {
  async getUser(id: string): Promise<any> {
    return 2;
  }
}
"""
    merged = _merge_ts_code(existing_ts, new_ts, "client.ts")
    assert merged.count("getUser(") == 1
