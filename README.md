# pifkid4

Bàn làm việc thông minh (ESP32Cam + ESP32)
Chức năng:
1. Nhắc nhở/hỗ trợ thói quen giúp cải thiện sức khỏe
- không nhìn màn hình quá lâu (<=20m) (quy tắc 2-2-2)
	+ Bộ đếm thời gian (cam chiếu vào mặt)
		=> sử dụng AI
	+ có LCD + LED chóp thông báo
	+ 2 nút (finished/skip)
	
- uống nước (in 3d bàn, có nơi để cốc kèm vòi, bình)
	+ sau 45m, tự rót nước vào ly 110ml
	+ LCD kêu uống nước, LED chóp
	+ tích hợp cảm biến cân nặng (thông báo không ngừng khi cảm biến vẫn nhận >= cân nặng ban đầu của cốc)

- suggest cung cấp đủ ánh sáng
	+ LCD suggest khi thiếu ánh sáng, Led chóp
	+ khi độ sáng đủ, thông báo stop, else ngược lại
	+ nút skip	
	
2. Bảo mật
- Khóa keypad cho tủ
	+ gửi dữ liệu khi tủ được mở (ngày tháng năm, thời gian)
- Khóa tủ online
	+ khóa tủ online

=> báo cáo dữ liệu

Chia việc:
=============================================
1. AI + Python DEV: Mxtwng 
Email: hoanmytang@gmail.com
SDT: 098718240
github user: mxtwng

Task:
- Face detec w/ esp32cam stream
- Implement 20min timer logic
- send alert signal esp32/update firebase

Use:
- OpenCV/MediaPipe (face detect)
- Python + serial/HTTP communication
- Firebase Admin SDK

=============================================
2. Embedded system DEV: Nhân
Email: ninhphucnhan1305@gmail.com
SDT: 0398797774
github user: nhan1305

Task:
- viet code cho ESP32
- xu li LCD, LEDs, button, pump, sensors, lock
- xu li tong tin, giao tiep voi Firebase (get & push data)

Use/Learn:
- Arduino/C++ cho ESP32
- Firebase-ESP-Client library
- I2C (LCD, BH1750), HX711 (load cell), GPIO (LEDs/buttons/servos)

=============================================
3. Hardware&Build Engi: Long
Email: buinhatbaolong2009@gmail.com
SDT: 0904342728
github user: sonhagrandma

Task:
- Lap ghep, noi day va modules
- thiet ke voi nuoc + cup holder
- lap keypad + khoa tu

Use/learn:
- solder/wiring
- motor/pump control (MOSFET/relay)
- 3d modeling basic

=============================================
4. Cloud&Firebase Engi: Mai
Email: maitn01432@gmail.com
SDT: 0869006449
github user: maitran3939

Task:
- thiet ke cau truc Firebase Database
- setup Firebase console/rules/dashboard
- thiet ke unlock online & data logging logic

Use/learn:
- Firebase Realtime Database (NoSQL)
- Firebase Console (rules, keys, usage)
- Javascript (cho dashboard)

=============================================

Git cmds:
- get repo: 
$ git clone https://github.com/username/repo.git

- check flow/version:
$ git status

- push code:
$ git add .
$ git commit -m "your-changes"
$ git push

- get newest code
$ git pull

- new branch
$ git checkout -b new-branch-name

- switch branch
$ git checkout branch-name