# 🌧️ Rain Gauge Maintenance Dashboard

ระบบติดตามและบำรุงรักษาสถานีวัดน้ำฝน สำหรับเจ้าหน้าที่ภาคสนาม

## ✨ Features

- 🔋 **สุขภาพแบตเตอรี่** - ติดตามสถานะแบตและโซล่าเซลล์
- 📋 **Priority List** - จัดลำดับความเร่งด่วนในการบำรุงรักษา
- 🗺️ **แผนที่** - แสดงตำแหน่งสถานีพร้อมสถานะ
- 📊 **รายงาน** - Export ข้อมูลเป็น CSV
- 🔍 **ตัวกรอง** - กรองตามสถานะ, แบตเตอรี่, timeout
- 📱 **Mobile-Friendly** - ใช้งานบนมือถือได้สะดวก

## 🚀 Quick Start

### วิธีที่ 1: Deploy บน Streamlit Cloud (แนะนำ)

1. Fork repo นี้
2. ไปที่ [streamlit.io/cloud](https://streamlit.io/cloud)
3. Sign in with GitHub
4. Deploy app จาก repo ของคุณ

### วิธีที่ 2: รันในเครื่อง

```bash
# Clone repo
git clone https://github.com/yourusername/rain-gauge-maintenance.git
cd rain-gauge-maintenance

# ติดตั้ง dependencies
pip install -r requirements.txt

# รัน app
streamlit run streamlit_app.py
```

## 📁 โครงสร้างไฟล์

```
rain-gauge-maintenance/
├── streamlit_app.py          # Frontend dashboard
├── main.py                   # Backend data fetcher
├── maintenance_dashboard.py  # Analysis logic
├── requirements.txt          # Python dependencies
├── .streamlit/
│   └── config.toml          # Streamlit config
├── stations.json            # Data file (generated)
└── README.md
```

## 📊 การใช้งาน

### 1. อัพโหลดข้อมูล

หากไม่มีไฟล์ `stations.json`:
- อัพโหลดไฟล์ผ่าน UI
- หรือใช้ข้อมูล Demo เพื่อทดลอง

### 2. สร้างข้อมูล

```bash
# รัน backend script
python main.py
```

สร้างไฟล์ `stations.json` อัตโนมัติ

### 3. ดู Dashboard

- เปิด `http://localhost:8501`
- หรือ URL ที่ Streamlit Cloud ให้

## 🔧 Configuration

แก้ไขเกณฑ์การประเมินใน `streamlit_app.py`:

```python
# แบตเตอรี่
battery_critical = 10.0  # < 10V = วิกฤต
battery_warning = 11.5   # < 11.5V = เตือน

# Timeout
timeout_critical = 24    # > 24 ชม. = วิกฤต
timeout_warning = 6      # > 6 ชม. = เตือน
```

## 📝 License

MIT License - ใช้งานได้ฟรี

## 🤝 Contributing

Pull requests are welcome!

## 📧 Contact

ติดต่อสอบถาม: your-email@example.com