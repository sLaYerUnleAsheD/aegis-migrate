       IDENTIFICATION DIVISION.
       PROGRAM-ID. AGE-CHECK.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 USER-AGE PIC 9(2) VALUE 25.
       PROCEDURE DIVISION.
       BEGIN.
           IF USER-AGE >= 18
               DISPLAY "Status: Adult"
           ELSE
               DISPLAY "Status: Minor"
           END-IF.
           STOP RUN.