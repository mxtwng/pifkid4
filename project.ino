#include <Wire.h>
#include <BH1750.h>
#include <LiquidCrystal_I2C.h>

BH1750 sensor;
LiquidCrystal_I2C lcd(0x27, 16, 2);
int ledPin = 16;
int button_skip = 20;

void setup() {
  Wire.begin(2, 1);
  sensor.begin();
  lcd.init();
  lcd.backlight();
  lcd.clear();
  pinMode(ledPin, OUTPUT);
  pinMode(button_skip, INPUT_PULLUP);
}

void clearLCDLine(int row) {
  lcd.setCursor(0, row);
  lcd.print("                "); 
  lcd.setCursor(0, row);
}

void loop() {
  float lux = sensor.readLightLevel();
  int luxInt = int(lux);

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Do sang: ");
  lcd.setCursor(0, 1);
  lcd.print(luxInt);


  if (luxInt <= 300) {

    lcd.setCursor(0, 1);
    lcd.print("khong du sang");
  }
  if (luxInt >= 750) {
    
    lcd.setCursor(0,1);
    lcd.print("qua sang");
  }

  if ((digitalRead(button_skip) == LOW) || (luxInt >= 300 && luxInt <= 500)) {
    clearLCDLine(1);
  }

  delay(500);
}