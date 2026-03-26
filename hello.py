import requests

for i in range(5):
    print(f"Hello, World! {i}")

for i in range(1,6):
    print(i)

my_set = {1, 2, 3, 4, 5}

response = requests.get("https://www.google.com")
print(response.status_code)