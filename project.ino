#include <WiFi.h>
#include <Wire.h>
#include <BH1750.h>
#include <LiquidCrystal_I2C.h>
#include <Firebase_ESP_Client.h>
// Timer for Firebase push
unsigned long lastPushMillis = 0;
const unsigned long pushInterval = 120000;  // 2 minutes in milliseconds
// Wi-Fi credentials
const char* WIFI_SSID = "PIF_CLUB";
const char* WIFI_PASSWORD = "chinsochin";

// Firebase credentials
#define FIREBASE_DATABASE_URL "https://embbed-e5898-default-rtdb.asia-southeast1.firebasedatabase.app"
#define FIREBASE_API_KEY "AIzaSyAJ1xY1PTDXyjcusMMLr0f4nqY5yamMfkA"

// Firebase objects
FirebaseData fbdo;
FirebaseJson json;
FirebaseConfig config;
FirebaseAuth auth;

// Light sensor and LCD
BH1750 lightMeter;
LiquidCrystal_I2C lcd(0x27, 16, 2);

// Light thresholds
const float LUX_TOO_DIM = 300.0;
const float LUX_TOO_BRIGHT = 750.0;

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);  // ESP32 default SDA/SCL
  lightMeter.begin();
  lcd.init();
  lcd.backlight();

  // Connect to Wi-Fi
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lcd.setCursor(0, 0); lcd.print("Connecting WiFi");
  Serial.print("Connecting to WiFi");
  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 40) {
    delay(500);
    Serial.print(".");
    retries++;
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\n❌ WiFi Failed!");
    lcd.clear(); lcd.setCursor(0, 0); lcd.print("WiFi Failed!");
    while (true);  // halt
  }

  Serial.println("\n✅ WiFi Connected!");
  lcd.clear(); lcd.setCursor(0, 0); lcd.print("WiFi Connected");

  // Setup Firebase
  config.api_key = FIREBASE_API_KEY;
  config.database_url = FIREBASE_DATABASE_URL;

  auth.user.email = "ninhphucnhan1305@gmail.com";      // Anonymous auth
  auth.user.password = "130509Nh@n";

  Firebase.begin(&config, &auth);
  Firebase.reconnectWiFi(true);

  Serial.println("Connecting to Firebase...");
  int attempts = 0;
  while (!Firebase.ready() && attempts < 50) {
    delay(100);
    Serial.print("*");
    attempts++;
  }

  if (Firebase.ready()) {
    Serial.println("\n✅ Firebase Ready!");
    lcd.setCursor(0, 1); lcd.print("Firebase Ready");
  } else {
    Serial.println("\n❌ Firebase Failed!");
    lcd.setCursor(0, 1); lcd.print("FB Failed!");
    while (true);
  }
}

void loop() {
  float lux = lightMeter.readLightLevel();
  const char* status;

  if (lux < LUX_TOO_DIM)
    status = "Too Dim";
  else if (lux > LUX_TOO_BRIGHT)
    status = "Too Bright";
  else
    status = "Normal";

  // Display on LCD
  lcd.clear();
  lcd.setCursor(0, 0); lcd.printf("Lux: %.1f", lux);
  lcd.setCursor(0, 1); lcd.print(status);
 if (millis() - lastPushMillis >= pushInterval) {
    lastPushMillis = millis();
  // Prepare JSON
  json.clear();
  json.set("lux", lux);
  json.set("status/value", status);
  json.set("status/dim", LUX_TOO_DIM);
  json.set("status/bright", LUX_TOO_BRIGHT);

  // Push to Firebase
  if (Firebase.RTDB.pushJSON(&fbdo, "/events", &json)) {
    Serial.println("✅ Data pushed: " + fbdo.pushName());
  } else {
    Serial.println("❌ Push failed: " + fbdo.errorReason());
  }
 }
  delay(2000);
}
