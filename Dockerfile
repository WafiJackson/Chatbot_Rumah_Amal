# 1. Gunakan OS Linux versi ringan yang sudah terinstal Python 3.10
FROM python:3.10-slim

# 2. Tetapkan folder kerja di dalam container
WORKDIR /code

# 3. Pindahkan file requirements.txt dari laptop ke dalam container
COPY ./app/requirements.txt /code/requirements.txt

# 4. Instal semua library yang dibutuhkan tanpa menyimpan cache (agar ukuran kecil)
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# 5. Pindahkan seluruh sisa kodemu (main.py dll) ke dalam container
COPY ./app /code/app

# 6. Pindahkan titik koordinat Docker masuk ke dalam folder app
WORKDIR /code/app

# 7. Karena sudah di dalam app, kita tinggal panggil "main:app" (tanpa app.main)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]