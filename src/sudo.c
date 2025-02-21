// Create a c program that will execute the command passed as an argument with the effective user id of the owner of the file.
// The command passed in must be checked against a whitelist of allowed commands so as to prevent abuse
// The whitelist should be stored in a file called /etc/allowed_commands

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <fcntl.h>

#define MAX_COMMAND_LENGTH 4096
#define MAX_OUTPUT_LENGTH 4096
#define ALLOWED_COMMANDS_FILE "/proj_risc/user_dev/bswan/tools_src/cadinstall/etc/allowed_commands"

int main(int argc, char *argv[]) {
    char *command;
    char *arguments[500];
    int i = 0;
    int noOfArgs = 0;

    if (argc < 2) {
        fprintf(stderr, "Usage: %s <command>\n", argv[0]);
        exit(1);
    }
 
    command = argv[1];

    for (i=1; i<argc; i++)
    {
        arguments[noOfArgs] = argv[i];
        noOfArgs++;
    }
    arguments[noOfArgs] = NULL;

    FILE *allowed_commands_file;
    char allowed_command[MAX_COMMAND_LENGTH];
    int allowed = 0;
   
    // Check if the allowed_commands file exists
    if (access(ALLOWED_COMMANDS_FILE, F_OK) == -1) {
        fprintf(stderr, "Allowed commands file does not exist: %s\n", ALLOWED_COMMANDS_FILE);
        exit(1);
    }
    allowed_commands_file = fopen(ALLOWED_COMMANDS_FILE, "r");
    if (allowed_commands_file == NULL) {
        perror("fopen");
        exit(1);
    }

    while (fgets(allowed_command, MAX_COMMAND_LENGTH, allowed_commands_file) != NULL) {  
        // remove the newline character
        allowed_command[strcspn(allowed_command, "\n")] = 0;

        // fprintf(stdout, "Checking command against:\n\t%s\n", allowed_command);
        if (strcmp(allowed_command, command) == 0) {
            allowed = 1;
            break;
        }

    }

    fclose(allowed_commands_file);

    if (!allowed) {
        fprintf(stderr, "Command not allowed to be run via this utility: %s\n",command);
        exit(1);
    }

    execvp(command, arguments);
    return 0;
}

/* The program should be compiled with the following command:
 gcc -o ../bin/.sudo sudo.c
 The program should be owned by cadtools and have the setuid bit set.
 sudo chown cadtools:vendor_tools ../bin/.sudo
 sudo chmod 755 ../bin/.sudo
 sudo chmod u+s ../bin/.sudo
*/
