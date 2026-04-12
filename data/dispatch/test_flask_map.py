from tools.get_spec.get_spec import SpecGetterFactory
flask_spec_getter = SpecGetterFactory.create(
    framework="flask", 
    project_dir="/Users/phuocpham/Desktop/BachPhuoc/Year4/DoAn/SelfDocAgent/data/CTFd", 
    mode="docker",
    output_dir="/Users/phuocpham/Desktop/BachPhuoc/Year4/DoAn/SelfDocAgent/DocGenAgent/output",
    compose_file="/Users/phuocpham/Desktop/BachPhuoc/Year4/DoAn/SelfDocAgent/data/CTFd/docker-compose.yml",
    service_name="ctfd",
    app_instance_path="CTFd.api:CTFd_API_v1"
)
script = flask_spec_getter._build_flask_map_script("/tmp/map_dump.json")
with open("temp_debug_flask.py", "w") as f:
    f.write(script)
print(script)
