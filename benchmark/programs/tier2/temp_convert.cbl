      * TEMPERATURE CONVERSION (tier 2): negative results, rounding
      * Record (8 bytes): SENSOR X(4) | FTEMP 9(3)V9
      * C = (F - 32) * 5 / 9, rounded to 2 decimals. The result is a
      * SIGNED field and prints with a fixed leading minus sign.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEMPCONV.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TEMP-FILE ASSIGN TO "input.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  TEMP-FILE.
       01  TEMP-REC.
           05 TC-SENSOR      PIC X(4).
           05 TC-F           PIC 9(3)V9.

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG       PIC X        VALUE "N".
           88 INPUT-DONE                  VALUE "Y".
       01  WS-C              PIC S9(3)V99 VALUE 0.
       01  WS-FREEZE         PIC 99       VALUE 0.
       01  WS-COUNT          PIC 99       VALUE 0.
       01  WS-F-ED           PIC ZZ9.9.
       01  WS-C-ED           PIC -ZZ9.99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT TEMP-FILE
           PERFORM READ-PARA
           PERFORM PROCESS-PARA UNTIL INPUT-DONE
           CLOSE TEMP-FILE
           DISPLAY "READINGS: " WS-COUNT " BELOW ZERO: " WS-FREEZE
           STOP RUN.

       READ-PARA.
           READ TEMP-FILE
               AT END SET INPUT-DONE TO TRUE
           END-READ.

       PROCESS-PARA.
           COMPUTE WS-C ROUNDED = (TC-F - 32) * 5 / 9
           IF WS-C < 0
               ADD 1 TO WS-FREEZE
           END-IF
           ADD 1 TO WS-COUNT
           MOVE TC-F TO WS-F-ED
           MOVE WS-C TO WS-C-ED
           DISPLAY TC-SENSOR " " WS-F-ED "F " WS-C-ED "C"
           PERFORM READ-PARA.